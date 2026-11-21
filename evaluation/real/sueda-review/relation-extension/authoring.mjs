import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import { Workbook } from '@oai/artifact-tool';
const root='/Users/suedasen/Desktop/trendscout-ai';
const base=root+'/evaluation/real';
const audit=base+'/sueda-review/relation-extension';
const input=await fs.readFile(audit+'/before-sueda-relations.csv','utf8');
const plan=JSON.parse(await fs.readFile(audit+'/repair-plan.json','utf8'));
if(crypto.createHash('sha256').update(input).digest('hex')!==plan.input_sha256)throw new Error('Workbook changed after repair planning.');
const wb=await Workbook.fromCSV(input,{sheetName:'Relations'});
const sh=wb.worksheets.getItem('Relations');
const headers=sh.getUsedRange().values[0];
const region='D128:G131';
sh.getRange('D128:D131').format.columnWidthPx=135;
sh.getRange('E128:E131').format.columnWidthPx=450;
sh.getRange('F128:F131').format.columnWidthPx=110;
sh.getRange('G128:G131').format.columnWidthPx=430;
sh.getRange(region).format.wrapText=true;
sh.getRange(region).format.rowHeightPx=110;
const apply=process.argv.includes('--apply');
if(apply){
 for(const cell of plan.literal_cells)sh.getRangeByIndexes(cell.row_index,cell.column_index,1,1).values=[["'"+cell.value]];
 for(const patch of plan.patches){
  if(sh.getRangeByIndexes(patch.row_index,0,1,1).values[0][0]!==patch.item_id)throw new Error('Posting ID/order changed.');
  for(const key of ['span_text','notes'])sh.getRangeByIndexes(patch.row_index,headers.indexOf(key),1,1).values=[[patch[key]]];
 }
}
wb.recalculate();
const preview=await wb.render({sheetName:'Relations',range:region,scale:1,format:'png'});
await fs.writeFile('/tmp/trendscout-relations-repair/'+(apply?'after':'before')+'.png',new Uint8Array(await preview.arrayBuffer()));
if(apply){
 const matrix=sh.getUsedRange().values;
 for(const cell of plan.literal_cells){const v=matrix[cell.row_index][cell.column_index];if(v!==cell.value&&v!=="'"+cell.value)throw new Error('Literal source-text preservation failed');matrix[cell.row_index][cell.column_index]=cell.value;}
 const quote=v=>{const s=v==null?'':String(v);return /[,"\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;};
 await fs.writeFile(audit+'/prepared-sueda-relations.csv',matrix.map(row=>row.map(quote).join(',')).join('\n')+'\n');
 console.log((await wb.inspect({kind:'region',sheetId:'Relations',range:region,maxChars:600})).ndjson);
}
