import { computed, ref, type Ref } from 'vue'
import { createLocalRowId } from '@/utils/localRowId'

type UsePhantomRowOptions<T> = {
  rows: () => readonly T[]
  makePhantom: () => T
  extraRows?: () => readonly T[]
}

export function usePhantomRow<T extends { __localId?: string }>({
  rows,
  makePhantom,
  extraRows = () => [],
}: UsePhantomRowOptions<T>) {
  // Every phantom this composable yields carries a fresh, stable `__localId` so
  // DataTable.getRowId keys it by identity, not array index — an index-keyed
  // phantom remounts (dropping focus) when its position shifts during a save.
  function freshPhantom(): T {
    return { ...makePhantom(), __localId: createLocalRowId() }
  }

  const phantomRow = ref(freshPhantom()) as Ref<T>

  const displayRows = computed<T[]>(() => [...rows(), ...extraRows(), phantomRow.value])
  const phantomIndex = computed(() => displayRows.value.length - 1)

  function isPhantom(row: T): boolean {
    return row === phantomRow.value
  }

  function isPhantomIndex(index: number): boolean {
    return index === phantomIndex.value
  }

  function resetPhantom(nextRow?: T): void {
    // An explicit nextRow already carries its own identity — keep it. A fresh
    // phantom gets a new `__localId` stamped by construction.
    phantomRow.value = nextRow ?? freshPhantom()
  }

  function promotePhantom(updates?: Partial<T>): T {
    const row = { ...phantomRow.value, ...updates } as T
    resetPhantom()
    return row
  }

  function selectPhantom(setSelectedIndex: (index: number) => void): void {
    setSelectedIndex(phantomIndex.value)
  }

  return {
    phantomRow,
    displayRows,
    phantomIndex,
    isPhantom,
    isPhantomIndex,
    resetPhantom,
    promotePhantom,
    selectPhantom,
  }
}
