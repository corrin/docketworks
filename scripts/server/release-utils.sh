#!/bin/bash
# Internal helpers for shared immutable releases. Source common.sh first.

release_path() {
    local sha="$1"
    echo "$RELEASES_DIR/$sha"
}

release_complete() {
    local sha="$1"
    local dir
    dir="$(release_path "$sha")"
    [[ -d "$dir" && -f "$dir/.complete" && -f "$dir/.release-sha" ]]
}

fetch_local_repo() {
    log "Fetching latest Git refs into $LOCAL_REPO..."
    sudo -u docketworks git -C "$LOCAL_REPO" fetch --prune origin
}

resolve_release_ref() {
    local ref="$1"
    sudo -u docketworks git -C "$LOCAL_REPO" rev-parse --verify "${ref}^{commit}"
}

resolve_existing_release_sha() {
    local ref="$1"
    local matches=()

    if release_complete "$ref"; then
        echo "$ref"
        return 0
    fi

    shopt -s nullglob
    matches=("$RELEASES_DIR"/"$ref"*)
    shopt -u nullglob
    if (( ${#matches[@]} == 1 )) && [[ -f "${matches[0]}/.complete" ]]; then
        basename "${matches[0]}"
        return 0
    fi

    resolve_release_ref "$ref"
}

instance_current_sha() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"
    local current_target="$instance_dir/current"

    if [[ -L "$current_target" && -f "$current_target/.release-sha" ]]; then
        cat "$current_target/.release-sha"
    elif [[ -d "$instance_dir/.git" ]]; then
        local inst_user
        inst_user="$(instance_user "$instance")"
        sudo -u "$inst_user" git -C "$instance_dir" rev-parse HEAD
    else
        echo ""
    fi
}

switch_instance_release() {
    local instance="$1"
    local sha="$2"
    local instance_dir="$INSTANCES_DIR/$instance"
    local tmp_link="$instance_dir/current.tmp"

    if ! release_complete "$sha"; then
        echo "ERROR: refusing to point $instance at incomplete/missing release $sha" >&2
        exit 1
    fi

    ln -sfn "../../releases/$sha" "$tmp_link"
    mv -Tf "$tmp_link" "$instance_dir/current"
}

ensure_release() {
    local sha="$1"
    local release_dir
    release_dir="$(release_path "$sha")"

    if release_complete "$sha"; then
        log "Release $sha already exists; reusing $release_dir"
        return 0
    fi

    mkdir -p "$RELEASES_DIR"
    chown docketworks:docketworks "$RELEASES_DIR"
    chmod 755 "$RELEASES_DIR"

    # Build directly at the final path. .complete (written last) is the only
    # completion gate, so an interrupted build leaves an incomplete, unreferenced
    # dir that we clear here and rebuild. Building in place (not build-then-mv)
    # keeps the venv's console-script shebangs valid — a moved venv is not
    # relocatable. Serial deploys mean there is no concurrent build to race.
    rm -rf "$release_dir"

    log "Building shared release $sha..."
    mkdir "$release_dir"
    chown docketworks:docketworks "$release_dir"

    if ! sudo -u docketworks bash -c "
        set -euo pipefail
        git -C '$LOCAL_REPO' archive '$sha' | tar -x -C '$release_dir'
        printf '%s\n' '$sha' > '$release_dir/.release-sha'
        python3.12 -m venv '$release_dir/.venv'
        export PATH='/opt/docketworks/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        export POETRY_VIRTUALENVS_CREATE=false
        export DOCKETWORKS_BUILD_SHA='$sha'
        source '$release_dir/.venv/bin/activate'
        pip install --upgrade pip
        cd '$release_dir'
        poetry install --no-interaction
        cd '$release_dir/frontend'
        REQUIRED_NODE_MAJOR=\$(sed -nE 's/^[[:space:]]*v?([0-9]+).*/\1/p' .nvmrc | head -n 1)
        if [[ -z \"\$REQUIRED_NODE_MAJOR\" ]]; then
            echo \"ERROR: Could not parse Node major from frontend/.nvmrc\" >&2
            exit 1
        fi
        CURRENT_NODE_MAJOR=\$(node --version | sed -E 's/^v([0-9]+).*/\1/')
        if [[ \"\$CURRENT_NODE_MAJOR\" != \"\$REQUIRED_NODE_MAJOR\" ]]; then
            echo \"ERROR: Node major \$CURRENT_NODE_MAJOR does not match frontend/.nvmrc (\$REQUIRED_NODE_MAJOR)\" >&2
            exit 1
        fi
        npm ci --include=dev --cache '$BASE_DIR/.npm-cache'
        npm run check:typed-router
        npm run build
        npm run manual:build
        rm -rf node_modules
        touch '$release_dir/.complete'
    "; then
        log "  ERROR: failed to build release $sha"
        rm -rf "$release_dir"
        exit 1
    fi

    log "Release $sha ready at $release_dir"
}

cleanup_incomplete_releases() {
    # Remove leftover release dirs from an interrupted build (no .complete
    # marker). Releases are built in place, so a crashed build can leave an
    # incomplete dir at the canonical path; the >1-day guard avoids touching a
    # build still in progress.
    mkdir -p "$RELEASES_DIR"
    local release_dir
    for release_dir in "$RELEASES_DIR"/*; do
        [[ -d "$release_dir" ]] || continue
        [[ -f "$release_dir/.complete" ]] && continue
        if [[ -n "$(find "$release_dir" -maxdepth 0 -mtime +0)" ]]; then
            log "Removing stale incomplete release build $(basename "$release_dir")"
            rm -rf "$release_dir"
        fi
    done
}

release_is_referenced() {
    local sha="$1"
    local instance_dir state_sha

    for instance_dir in "$INSTANCES_DIR"/*; do
        [[ -d "$instance_dir" ]] || continue
        if [[ -L "$instance_dir/current" && "$(readlink -f "$instance_dir/current")" == "$(release_path "$sha")" ]]; then
            return 0
        fi
        if [[ -f "$instance_dir/deploy-state.env" ]]; then
            state_sha="$(read_env_value "$instance_dir/deploy-state.env" PREVIOUS_SHA)"
            if [[ "$state_sha" == "$sha" ]]; then
                return 0
            fi
        fi
    done
    return 1
}

cleanup_unreferenced_releases() {
    local protected_sha="${1:-}"
    local release_dir sha

    mkdir -p "$RELEASES_DIR"
    for release_dir in "$RELEASES_DIR"/*; do
        [[ -d "$release_dir" && -f "$release_dir/.complete" ]] || continue
        sha="$(basename "$release_dir")"
        if [[ -n "$protected_sha" && "$sha" == "$protected_sha" ]]; then
            continue
        fi
        if release_is_referenced "$sha"; then
            continue
        fi
        log "Removing unreferenced release $sha"
        rm -rf "$release_dir"
    done
}

compact_legacy_instance_checkout() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"

    [[ -d "$instance_dir/.git" ]] || return 0

    log "  Compacting legacy checkout payload for $instance..."
    local name path
    for path in "$instance_dir"/* "$instance_dir"/.[!.]* "$instance_dir"/..?*; do
        [[ -e "$path" ]] || continue
        name="$(basename "$path")"
        case "$name" in
            .|..|.env|.env.tmp.*|.fqdn|.dr-mode|.bash_profile|current|deploy-state.env|gcp-credentials.json|logs|mediafiles|dropbox|phone-recordings|session-replays|backups|fixtures|.fixtures)
                ;;
            gunicorn.sock)
                ;;
            *)
                rm -rf "$path"
                ;;
        esac
    done
    log "  Legacy checkout payload compacted for $instance"
}
