import type { HTMLAttributes } from 'vue'

/**
 * Table — semantic data table built from plain HTML table elements
 * (no reka-ui primitive). Compose the parts to build a table.
 *
 * @slot default — table parts (TableHeader, TableBody, TableFooter, TableCaption)
 */
export interface TableProps {
  class?: HTMLAttributes['class']
}

/** Wraps <thead>. @slot default — TableRow(s) of TableHead cells */
export interface TableHeaderProps {
  class?: HTMLAttributes['class']
}

/** Wraps <tbody>. @slot default — TableRow(s) */
export interface TableBodyProps {
  class?: HTMLAttributes['class']
}

/** Wraps <tfoot>, muted background. @slot default — TableRow(s) */
export interface TableFooterProps {
  class?: HTMLAttributes['class']
}

/** Wraps <tr>; hover + selected (data-[state=selected]) styling. @slot default — cells */
export interface TableRowProps {
  class?: HTMLAttributes['class']
}

/** Wraps <th> header cell. @slot default — header content */
export interface TableHeadProps {
  class?: HTMLAttributes['class']
}

/** Wraps <td> data cell. @slot default — cell content */
export interface TableCellProps {
  class?: HTMLAttributes['class']
}

/** Wraps <caption>, muted text below the table. @slot default — caption text */
export interface TableCaptionProps {
  class?: HTMLAttributes['class']
}

/**
 * Convenience row for an empty state. Renders a single full-width
 * centered cell (TableRow > TableCell) spanning `colspan` columns.
 * @slot default — empty-state content
 */
export interface TableEmptyProps {
  class?: HTMLAttributes['class']
  /** Number of columns to span. @default 1 */
  colspan?: number
}

export declare const Table: import('vue').DefineComponent<TableProps>
export declare const TableHeader: import('vue').DefineComponent<TableHeaderProps>
export declare const TableBody: import('vue').DefineComponent<TableBodyProps>
export declare const TableFooter: import('vue').DefineComponent<TableFooterProps>
export declare const TableRow: import('vue').DefineComponent<TableRowProps>
export declare const TableHead: import('vue').DefineComponent<TableHeadProps>
export declare const TableCell: import('vue').DefineComponent<TableCellProps>
export declare const TableCaption: import('vue').DefineComponent<TableCaptionProps>
export declare const TableEmpty: import('vue').DefineComponent<TableEmptyProps>
