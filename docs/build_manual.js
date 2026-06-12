/*
 * build_manual.js — regenerate docs/USER_MANUAL.docx from docs/USER_MANUAL.md.
 *
 * Why this script exists:
 *   docx-js emits the Table of Contents as an EMPTY field. Until Word repaginates
 *   (F9), every TOC entry shows page 1. Distributed to non-Word viewers it stays
 *   wrong. So after generating the docx we bake real page numbers into the TOC,
 *   computed from a rendered PDF, and wrap each entry as a bookmark hyperlink so
 *   navigation still works and Word can still update it normally.
 *
 * Usage (from repo root):
 *   node docs/build_manual.js
 *
 * Requirements:
 *   - npm i -g docx            (Node docx library)
 *   - python3 with pdfplumber  (pip install pdfplumber --break-system-packages)
 *   - the docx skill's office helpers at /mnt/skills/public/docx/scripts/office
 *     (soffice.py for PDF render, unpack.py/pack.py for the XML edit)
 *
 * If the office helpers are not present (e.g. outside the build environment),
 * the script still writes a valid docx — only the TOC-number bake step is skipped,
 * and the TOC will show page 1 until the reader presses F9 in Word.
 *
 * IMPORTANT (handoff): editing USER_MANUAL.md then re-running this script is the
 * supported way to update the manual. Do NOT hand-edit the .docx.
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType,
  ShadingType, TableOfContents, PageBreak, ImageRun, Header, Footer, PageNumber
} = require('docx');

const DOCS = __dirname;
const IMG = path.join(DOCS, 'img');
const MD = path.join(DOCS, 'USER_MANUAL.md');
const OUT = path.join(DOCS, 'USER_MANUAL.docx');
const OFFICE = '/mnt/skills/public/docx/scripts/office';
const CONTENT_W = 9360; // US Letter, 1" margins

// ---------- inline formatting: **bold** (may wrap `code`), *italic*, `code` ----------
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*.+?\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const tok = m[0];
    if (tok.startsWith('**')) {
      const inner = tok.slice(2, -2);
      for (const p of inner.split(/(`[^`]+`)/)) {
        if (!p) continue;
        if (p.startsWith('`') && p.endsWith('`'))
          out.push(new TextRun({ text: p.slice(1, -1), bold: true, font: 'Consolas', ...base }));
        else
          out.push(new TextRun({ text: p, bold: true, ...base }));
      }
    } else if (tok.startsWith('*')) {
      out.push(new TextRun({ text: tok.slice(1, -1), italics: true, ...base }));
    } else {
      out.push(new TextRun({ text: tok.slice(1, -1), font: 'Consolas', ...base }));
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  if (out.length === 0) out.push(new TextRun({ text: '', ...base }));
  return out;
}

const border = { style: BorderStyle.SINGLE, size: 1, color: 'BFBFBF' };
const cellBorders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 120, right: 120 };

function makeTable(rows) {
  const ncol = rows[0].length;
  const colW = Math.floor(CONTENT_W / ncol);
  const widths = Array(ncol).fill(colW);
  widths[ncol - 1] = CONTENT_W - colW * (ncol - 1);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((cells, ri) => new TableRow({
      tableHeader: ri === 0,
      children: cells.map((c, ci) => new TableCell({
        borders: cellBorders, margins: cellMargins,
        width: { size: widths[ci], type: WidthType.DXA },
        shading: ri === 0 ? { fill: 'D9E2F3', type: ShadingType.CLEAR } : undefined,
        children: [new Paragraph({ spacing: { before: 20, after: 20 },
          children: runs(c.trim(), ri === 0 ? { bold: true } : {}) })],
      })),
    })),
  });
}

function codeBlock(lines) {
  return new Paragraph({
    shading: { fill: 'F2F2F2', type: ShadingType.CLEAR },
    spacing: { before: 80, after: 80 }, indent: { left: 120 },
    children: lines.flatMap((ln, i) => {
      const r = new TextRun({ text: ln || ' ', font: 'Consolas', size: 18 });
      return i === 0 ? [r] : [new TextRun({ break: 1, font: 'Consolas', size: 18 }), r];
    }),
  });
}

const IMG_DIMS = {}; // filled lazily
function imgDims(file) {
  if (IMG_DIMS[file]) return IMG_DIMS[file];
  // read PNG width/height from the IHDR chunk
  const b = fs.readFileSync(path.join(IMG, file));
  const w = b.readUInt32BE(16), h = b.readUInt32BE(20);
  return (IMG_DIMS[file] = [w, h]);
}
function imagePara(file, caption) {
  const [w, h] = imgDims(file);
  const scale = Math.min(1, 480 / w);
  const data = fs.readFileSync(path.join(IMG, file));
  const out = [new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 120, after: 40 },
    children: [new ImageRun({ data, type: file.split('.').pop(),
      transformation: { width: Math.round(w * scale), height: Math.round(h * scale) } })],
  })];
  if (caption) out.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 160 },
    children: [new TextRun({ text: caption, italics: true, size: 18, color: '595959' })],
  }));
  return out;
}

// ---------- parse the markdown ----------
const lines = fs.readFileSync(MD, 'utf8').split('\n');
const body = [];
let i = 0, numListSeq = 0;
const numberingConfigs = [
  { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '\u2022',
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } }] },
];
function flushTable(buf) {
  const rows = buf.filter(r => !/^\s*\|?\s*-{2,}/.test(r))
    .map(r => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim()));
  body.push(makeTable(rows));
  body.push(new Paragraph({ text: '', spacing: { after: 80 } }));
}
while (i < lines.length) {
  let ln = lines[i];
  const img = ln.match(/^!\[(.*?)\]\(img\/(.+?)\)\s*$/);
  if (img) { imagePara(img[2], img[1]).forEach(p => body.push(p)); i++; continue; }
  if (/^```/.test(ln)) { const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; } i++; body.push(codeBlock(buf)); continue; }
  if (/^\s*\|/.test(ln)) { const buf = []; while (i < lines.length && /^\s*\|/.test(lines[i])) { buf.push(lines[i].trim()); i++; } flushTable(buf); continue; }
  let m;
  if ((m = ln.match(/^#\s+(.*)/)))    { body.push(new Paragraph({ heading: HeadingLevel.TITLE,    spacing: { after: 240 }, children: runs(m[1]) })); i++; continue; }
  if ((m = ln.match(/^##\s+(.*)/)))   { body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: runs(m[1]) })); i++; continue; }
  if ((m = ln.match(/^###\s+(.*)/)))  { body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: runs(m[1]) })); i++; continue; }
  if ((m = ln.match(/^####\s+(.*)/))) { body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: runs(m[1]) })); i++; continue; }
  if (/^---\s*$/.test(ln)) { i++; continue; }
  if (/^>\s?/.test(ln)) {
    const buf = []; while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++; }
    body.push(new Paragraph({ shading: { fill: 'FFF6E0', type: ShadingType.CLEAR },
      indent: { left: 360 }, spacing: { before: 80, after: 120 }, children: runs(buf.join(' ')) }));
    continue;
  }
  if (/^[-*]\s+/.test(ln)) {
    while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
      let t = lines[i].replace(/^[-*]\s+/, ''); i++;
      while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*\|/.test(lines[i]) && !/^[-*]\s/.test(lines[i].trim())) { t += ' ' + lines[i].trim(); i++; }
      body.push(new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 40 }, children: runs(t) }));
    }
    continue;
  }
  if (/^\d+\.\s+/.test(ln)) {
    numListSeq++; const ref = 'numbers' + numListSeq;
    numberingConfigs.push({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } }] });
    while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
      let t = lines[i].replace(/^\d+\.\s+/, ''); i++;
      while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*\|/.test(lines[i])) { t += ' ' + lines[i].trim(); i++; }
      body.push(new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 40 }, children: runs(t) }));
    }
    continue;
  }
  if (/^\s*$/.test(ln)) { i++; continue; }
  const buf = [ln]; i++;
  while (i < lines.length && lines[i].trim() !== '' && !/^[#>|`!-]/.test(lines[i]) && !/^\d+\.\s/.test(lines[i]) && !/^[-*]\s/.test(lines[i])) { buf.push(lines[i]); i++; }
  body.push(new Paragraph({ spacing: { after: 120 }, children: runs(buf.join(' ')) }));
}

// ---------- assemble ----------
const styles = {
  default: { document: { run: { font: 'Arial', size: 21 } } },
  paragraphStyles: [
    { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 44, bold: true, font: 'Arial', color: '1F3864' }, paragraph: { spacing: { after: 120 }, outlineLevel: 0 } },
    { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 30, bold: true, font: 'Arial', color: '1F3864' }, paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 0 } },
    { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 25, bold: true, font: 'Arial', color: '2E5496' }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 22, bold: true, font: 'Arial', color: '2E5496' }, paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 } },
  ],
};
const cover = [
  body[0],
  new Paragraph({ children: [new TextRun({ text: 'incadea / BC-NAV v14 cumulative-update merge tool', size: 24, color: '595959' })], spacing: { after: 80 } }),
  new Paragraph({ children: [new TextRun({ text: 'User Manual and Rules Index', size: 22, color: '595959' })], spacing: { after: 400 } }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('Contents')] }),
  new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-3' }),
  new Paragraph({ children: [new PageBreak()] }),
];
const doc = new Document({
  styles, numbering: { config: numberingConfigs }, features: { updateFields: true },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: 'CUupdateTool — User Manual', size: 16, color: '808080' })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'Page ', size: 16, color: '808080' }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: '808080' })] })] }) },
    children: [...cover, ...body.slice(1)],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log('wrote', path.relative(process.cwd(), OUT), buf.length, 'bytes');
  try { bakeTOC(); } catch (e) { console.warn('TOC bake skipped:', e.message, '\n(TOC will show page 1 until Word F9.)'); }
});

// ---------- bake real TOC page numbers (see header comment) ----------
function bakeTOC() {
  if (!fs.existsSync(OFFICE)) throw new Error('office helpers not found at ' + OFFICE);
  const tmp = fs.mkdtempSync('/tmp/manbuild_');
  // 1. render PDF
  execFileSync('python3', [path.join(OFFICE, 'soffice.py'), '--headless', '--convert-to', 'pdf', '--outdir', tmp, OUT], { stdio: 'ignore' });
  const pdf = path.join(tmp, path.basename(OUT).replace(/\.docx$/, '.pdf'));
  // 2. heading list from the md (Title + #..#### in order)
  const heads = [];
  for (const l of fs.readFileSync(MD, 'utf8').split('\n')) {
    const mm = l.match(/^(#{1,4})\s+(.*)/); if (!mm) continue;
    let t = mm[2].trim().replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1').replace(/\*(.+?)\*/g, '$1');
    heads.push({ level: mm[1].length, text: t });
  }
  // 3. page per heading via python+pdfplumber
  const mapJson = path.join(tmp, 'map.json');
  fs.writeFileSync(path.join(tmp, 'h.json'), JSON.stringify(heads));
  const py = `
import json,re,pdfplumber
heads=json.load(open(r'${path.join(tmp, 'h.json')}'))
norm=lambda s:re.sub(r'\\s+',' ',s).strip().lower()
pt=[]
with pdfplumber.open(r'${pdf}') as pdf:
    for p in pdf.pages: pt.append(norm(p.extract_text() or ''))
out=[];frm=0
for h in heads:
    k=norm(h['text']);pg=1
    for pi in range(frm,len(pt)):
        if k in pt[pi]: pg=pi+1;break
    else:
        for pi in range(len(pt)):
            if k in pt[pi]: pg=pi+1;break
    out.append({**h,'page':pg});frm=max(frm,pg-1)
json.dump(out,open(r'${mapJson}','w'))
`;
  execFileSync('python3', ['-c', py], { stdio: 'ignore' });
  const toc = JSON.parse(fs.readFileSync(mapJson, 'utf8')).map((e, idx) => ({ ...e, bm: `_Toc_cu_${idx}` }));
  // 4. unpack docx, inject bookmarks + replace empty TOC field
  const un = path.join(tmp, 'un');
  execFileSync('python3', [path.join(OFFICE, 'unpack.py'), OUT, un], { stdio: 'ignore' });
  const docXmlPath = path.join(un, 'word', 'document.xml');
  let x = fs.readFileSync(docXmlPath, 'utf8');
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  let bmid = 9000;
  for (const e of toc) {
    const needle = `<w:t xml:space="preserve">${esc(e.text)}</w:t>`;
    const at = x.indexOf(needle);
    if (at === -1) { console.warn('  TOC bookmark miss:', e.text); bmid++; continue; }
    const rs = x.lastIndexOf('<w:r>', at);
    const re_ = x.indexOf('</w:r>', at) + 6;
    x = x.slice(0, rs) + `<w:bookmarkStart w:id="${bmid}" w:name="${e.bm}"/>` + x.slice(rs, re_) + `<w:bookmarkEnd w:id="${bmid}"/>` + x.slice(re_);
    bmid++;
  }
  const entry = e => {
    const indent = { 1: 0, 2: 0, 3: 360, 4: 720 }[e.level] || 0;
    const ind = indent ? `<w:ind w:left="${indent}"/>` : '';
    return '<w:p><w:pPr>'
      + '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9360"/></w:tabs>'
      + '<w:spacing w:after="40"/>' + ind
      + '<w:rPr><w:noProof/></w:rPr></w:pPr>'
      + `<w:hyperlink w:anchor="${e.bm}"><w:r><w:rPr><w:noProof/></w:rPr><w:t xml:space="preserve">${esc(e.text)}</w:t></w:r></w:hyperlink>`
      + '<w:r><w:rPr><w:noProof/></w:rPr><w:tab/></w:r>'
      + `<w:hyperlink w:anchor="${e.bm}"><w:r><w:rPr><w:noProof/></w:rPr><w:t>${e.page}</w:t></w:r></w:hyperlink>`
      + '</w:p>';
  };
  const scS = x.indexOf('<w:sdtContent>'), scE = x.indexOf('</w:sdtContent>', scS);
  const newSC = '<w:sdtContent>'
    + '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    + '<w:r><w:instrText xml:space="preserve">TOC \\h \\o &quot;1-3&quot;</w:instrText></w:r>'
    + '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
    + toc.map(entry).join('')
    + '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    + '</w:sdtContent>';
  x = x.slice(0, scS) + newSC + x.slice(scE + '</w:sdtContent>'.length);
  fs.writeFileSync(docXmlPath, x);
  // 5. repack over the original
  execFileSync('python3', [path.join(OFFICE, 'pack.py'), un, OUT, '--original', OUT], { stdio: 'inherit' });
  console.log('baked TOC page numbers for', toc.length, 'entries');
}
