import { Document, Packer, Paragraph, PageOrientation } from '/Users/hitsz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/docx/dist/index.mjs';
import { writeFile } from 'node:fs/promises';
const variants = [
  ['a', 23811, 16838],
  ['b', 16838, 23811],
  ['c', 16838, 11906],
  ['d', 11906, 16838],
];
for (const [name, width, height] of variants) {
  const doc = new Document({sections: [{properties: {page: {size: {orientation: PageOrientation.LANDSCAPE, width, height}, margin: {top: 720, bottom: 720, left: 720, right: 720}}}, children: [new Paragraph(`variant ${name} ${width}x${height}`)]}]});
  const blob = await Packer.toBlob(doc);
  await writeFile(`/Users/hitsz/equipment research/.tmp-docx-qa/page-${name}.docx`, Buffer.from(await blob.arrayBuffer()));
}
