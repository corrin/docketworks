import { computed, ref, type Ref } from 'vue'

type UsePhantomRowOptions<T> = {
  rows: () => readonly T[]
  makePhantom: () => T
  extraRows?: () => readonly T[]
}

export function usePhantomRow<T>({
  rows,
  makePhantom,
  extraRows = () => [],
}: UsePhantomRowOptions<T>) {
  const phantomRow = ref(makePhantom()) as Ref<T>

  const displayRows = computed<T[]>(() => [...rows(), ...extraRows(), phantomRow.value])
  const phantomIndex = computed(() => displayRows.value.length - 1)

  function isPhantom(row: T): boolean {
    return row === phantomRow.value
  }

  function isPhantomIndex(index: number): boolean {
    return index === phantomIndex.value
  }

  function resetPhantom(nextRow?: T): void {
    phantomRow.value = nextRow ?? makePhantom()
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
