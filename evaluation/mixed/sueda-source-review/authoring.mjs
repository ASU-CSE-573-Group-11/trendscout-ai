import fs from 'node:fs/promises';
import { Workbook } from '@oai/artifact-tool';
const root='/Users/suedasen/Desktop/trendscout-ai';
const directory=root+'/evaluation/mixed';
const audit=directory+'/sueda-source-review';
const plan=JSON.parse(await fs.readFile(audit+'/decision-plan.json','utf8'));
const quote=value=>{
  const text=value==null?'':String(value);
  return /[,"\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;
};
for (const item of plan.files) {
  const workbook=await Workbook.fromCSV(await fs.readFile(directory+'/workbooks/'+item.file,'utf8'),{sheetName:'Review'});
  const sheet=workbook.worksheets.getItem('Review');
  const headers=sheet.getUsedRange().values[0];
  for(const key of Object.keys(item.updates[0])) {
    const column=headers.indexOf(key);
    if(column<0)throw new Error('Missing target column: '+key);
    sheet.getRangeByIndexes(1,column,item.updates.length,1).values=item.updates.map(update=>[update[key]]);
  }
  workbook.recalculate();
  console.log((await workbook.inspect({kind:'region',sheetId:'Review',range:item.file==='qrels.csv'?'E1:I3':'E1:H4',maxChars:1100})).ndjson);
  const matrix=sheet.getRangeByIndexes(0,0,item.updates.length+1,headers.length).values;
  await fs.writeFile(audit+'/prepared-'+item.file,matrix.map(row=>row.map(quote).join(',')).join('\n')+'\n');
  if(item.file==='sueda-entities.csv') {
    sheet.getRange('E1:E5').format.columnWidthPx=130;
    sheet.getRange('F1:F5').format.columnWidthPx=450;
    sheet.getRange('G1:G5').format.columnWidthPx=110;
    sheet.getRange('H1:H5').format.columnWidthPx=510;
    sheet.getRange('E1:H5').format.wrapText=true;
    sheet.getRange('E1:H5').format.rowHeightPx=80;
    const preview=await workbook.render({sheetName:'Review',range:'E1:H5',scale:1,format:'png'});
    await fs.writeFile('/tmp/trendscout-mixed-review/after.png',new Uint8Array(await preview.arrayBuffer()));
  }
}
