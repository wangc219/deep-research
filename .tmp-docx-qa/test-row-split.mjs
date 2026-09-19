import {Document,Packer,Paragraph,Table,TableRow,TableCell,TextRun,WidthType,PageOrientation,TableLayoutType,BorderStyle,ShadingType,VerticalAlign} from '/Users/hitsz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/docx/dist/index.mjs';
import {writeFile} from 'node:fs/promises';
const long='这是一段用于验证长文本分页完整性的测试内容。'.repeat(900);
const border={style:BorderStyle.SINGLE,size:1,color:'D9D9D9'};
for (const [name,cantSplit] of [['header-only',false],['all-rows',true]]) {
 const rows=[['装备','概述'],['超长装备',long]].map((line,i)=>new TableRow({tableHeader:i===0,cantSplit:i===0||cantSplit,children:line.map(cell=>new TableCell({width:{size:i?6000:3000,type:WidthType.DXA},verticalAlign:VerticalAlign.TOP,shading:i===0?{fill:'EAF0FF',type:ShadingType.SOLID}:undefined,children:[new Paragraph({children:[new TextRun({text:cell,size:17})]})]}))}));
 const doc=new Document({sections:[{properties:{page:{size:{orientation:PageOrientation.LANDSCAPE,width:16838,height:23811},margin:{top:720,bottom:720,left:720,right:720}}},children:[new Table({width:{size:100,type:WidthType.PERCENTAGE},columnWidths:[6000,15000],layout:TableLayoutType.FIXED,borders:{top:border,bottom:border,left:border,right:border,insideHorizontal:border,insideVertical:border},rows})]}]});
 const b=await Packer.toBlob(doc); await writeFile(`/Users/hitsz/equipment research/.tmp-docx-qa/${name}.docx`,Buffer.from(await b.arrayBuffer()));
}
