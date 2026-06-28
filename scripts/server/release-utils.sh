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

instance_app_link_path() {
    local instance="$1"
    echo "$INSTANCES_DIR/$instance/app"
}

instance_legacy_current_link_path() {
    local instance="$1"
    echo "$INSTANCES_DIR/$instance/current"
}

short_release_sha() {
    local sha="$1"
    printf "%s\n" "${sha:0:8}"
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

newest_predeploy_backup_for_sha() {
    local backup_dir="$1"
    local short_sha="$2"
    local matches=()
    local sorted=()

    if [[ ! "$short_sha" =~ ^[0-9a-f]{8}$ ]]; then
        echo "ERROR: rollback hash must be an 8-character lowercase hex SHA prefix: $short_sha" >&2
        return 1
    fi

    shopt -s nullglob
    matches=("$backup_dir"/predeploy_*_"$short_sha".sql.gz)
    shopt -u nullglob
    if (( ${#matches[@]} == 0 )); then
        return 1
    fi

    # Filenames contain YYYYMMDD_HHMMSS so lexicographic sort == chronological;
    # last element is newest.
    mapfile -t sorted < <(printf '%s\n' "${matches[@]}" | sort)
    printf "%s\n" "${sorted[-1]}"
}

instance_current_sha() {
    local instance="$1"
    local app_target
    local legacy_current_target
    app_target="$(instance_app_link_path "$instance")"
    legacy_current_target="$(instance_legacy_current_link_path "$instance")"

    if [[ -L "$app_target" && -f "$app_target/.release-sha" ]]; then
        cat "$app_target/.release-sha"
    elif [[ -L "$legacy_current_target" && -f "$legacy_current_target/.release-sha" ]]; then
        cat "$legacy_current_target/.release-sha"
    else
        echo ""
    fi
}

switch_instance_release() {
    local instance="$1"
    local sha="$2"
    local instance_dir="$INSTANCES_DIR/$instance"
    local app_target
    local tmp_link="$instance_dir/app.tmp"
    app_target="$(instance_app_link_path "$instance")"

    if ! release_complete "$sha"; then
        echo "ERROR: refusing to point $instance at incomplete/missing release $sha" >&2
        exit 1
    fi

    ln -sfn "../../releases/$sha" "$tmp_link"
    mv -Tf "$tmp_link" "$app_target"
}

ensure_instance_app_link() {
    local instance="$1"
    local app_target
    local legacy_current_target
    app_target="$(instance_app_link_path "$instance")"
    legacy_current_target="$(instance_legacy_current_link_path "$instance")"

    if [[ -L "$app_target" && -L "$legacy_current_target" ]]; then
        if [[ "$(readlink -f "$app_target")" != "$(readlink -f "$legacy_current_target")" ]]; then
            echo "ERROR: $instance has divergent app and current release links." >&2
            echo "  app -> $(readlink -f "$app_target")" >&2
            echo "  current -> $(readlink -f "$legacy_current_target")" >&2
            return 1
        fi
    elif [[ ! -L "$app_target" && -L "$legacy_current_target" ]]; then
        ln -sfn "$(readlink "$legacy_current_target")" "$app_target"
    else
        :
    fi
}

remove_legacy_current_link() {
    local instance="$1"
    local app_target
    local legacy_current_target
    app_target="$(instance_app_link_path "$instance")"
    legacy_current_target="$(instance_legacy_current_link_path "$instance")"

    if [[ ! -L "$legacy_current_target" ]]; then
        return 0
    fi
    if [[ ! -L "$app_target" ]]; then
        echo "ERROR: refusing to remove $legacy_current_target before $app_target exists." >&2
        return 1
    fi
    if [[ "$(readlink -f "$app_target")" != "$(readlink -f "$legacy_current_target")" ]]; then
        echo "ERROR: refusing to remove divergent legacy current link for $instance." >&2
        return 1
    fi
    rm -f "$legacy_current_target"
}

write_deploy_state() {
    local instance="$1"
    local previous_sha="$2"
    local current_sha="$3"
    local inst_user="$4"
    local instance_dir="$INSTANCES_DIR/$instance"

    {
        echo "PREVIOUS_SHA=$(short_release_sha "$previous_sha")"
        echo "CURRENT_SHA=$(short_release_sha "$current_sha")"
        echo "DEPLOYED_AT=$(date --iso-8601=seconds)"
    } > "$instance_dir/deploy-state.env"
    chown "$inst_user:$inst_user" "$instance_dir/deploy-state.env"
    chmod 600 "$instance_dir/deploy-state.env"
}

state_sha_references_release() {
    local state_sha="$1"
    local release_sha="$2"

    [[ -n "$state_sha" ]] || return 1
    [[ "$state_sha" =~ ^[0-9a-f]{8}$ ]] || return 1
    [[ "$(short_release_sha "$release_sha")" == "$state_sha" ]]
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
    local instance_dir instance app_target state_sha

    for instance_dir in "$INSTANCES_DIR"/*; do
        [[ -d "$instance_dir" ]] || continue
        instance="$(basename "$instance_dir")"
        app_target="$(instance_app_link_path "$instance")"
        if [[ -L "$app_target" && "$(readlink -f "$app_target")" == "$(release_path "$sha")" ]]; then
            return 0
        fi
        if [[ -f "$instance_dir/deploy-state.env" ]]; then
            state_sha="$(read_env_value "$instance_dir/deploy-state.env" PREVIOUS_SHA)"
            if state_sha_references_release "$state_sha" "$sha"; then
                return 0
            fi
        fi
    done
    return 1
}

cleanup_unreferenced_releases() {
    local protected_sha="${1:-}"
    local instance_dir
    local release_dir sha

    for instance_dir in "$INSTANCES_DIR"/*; do
        [[ -d "$instance_dir" ]] || continue
        ensure_instance_app_link "$(basename "$instance_dir")"
    done

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
