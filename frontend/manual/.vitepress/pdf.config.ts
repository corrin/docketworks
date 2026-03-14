import { defineUserConfig } from 'vitepress-export-pdf'

export default defineUserConfig({
  outFile: 'jobs-manager-training-manual.pdf',
  outDir: '../dist-manual',

  pdfOptions: {
    format: 'A4',
    margin: {
      top: '60px',
      bottom: '60px',
      left: '40px',
      right: '40px',
    },
    printBackground: true,
  },

  // Include all pages except 404
  routePatterns: ['/**', '!/404.html'],

  // Enable PDF outlines (bookmarks/table of contents)
  pdfOutlines: true,
})
