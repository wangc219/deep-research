import { Document, Packer, Paragraph, Table, TableRow, TableCell, TextRun, WidthType } from '/Users/hitsz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/docx/dist/index.mjs';
import { writeFile } from 'node:fs/promises';
const t = new Table({ width:{size:100,type:WidthType.PERCENTAGE}, rows:[['TITLE','BETA'],['hello world','second cell'],['long words in a narrow table cell to wrap','another line']].map((r,i)=>new TableRow({children:r.map(c=>new TableCell({children:[new Paragraph({children:[new TextRun({text:c,bold:i===0,size:18})]})]}))})) });
const d = new Document({sections:[{children:[new Paragraph({text:'TITLE TEST'}),t]}]});
await writeFile('.tmp-docx-qa/latin_test.docx',Buffer.from(await (await Packer.toBlob(d)).arrayBuffer()));
