#!/usr/bin/env node
/**
 * 企业微信智能表格创建工具
 * 通过 wecom-cli 创建完整的智能表格
 */

import { execSync } from 'child_process';

const log = console.error;

function runWecom(cmd, jsonArg) {
  let fullCmd;
  if (jsonArg) {
    fullCmd = `wecom-cli ${cmd} --json '${JSON.stringify(jsonArg)}'`;
  } else {
    fullCmd = `wecom-cli ${cmd}`;
  }
  log(`[wecom] ${fullCmd}`);

  try {
    const output = execSync(fullCmd, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
    return output;
  } catch (e) {
    log(`[wecom] Error: ${e.message}`);
    throw e;
  }
}

function parseResult(stdout) {
  try {
    const outer = JSON.parse(stdout);
    const content = outer?.result?.content?.[0]?.text;
    return content ? JSON.parse(content) : { errcode: -1, errmsg: 'empty result' };
  } catch (e) {
    log(`[wecom] Parse error: ${e.message}`);
    return { errcode: -1, errmsg: 'parse error' };
  }
}

function run(cmd, jsonArg) {
  return parseResult(runWecom(cmd, jsonArg));
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function mapFieldType(type) {
  const typeMap = {
    'TEXT': 'FIELD_TYPE_TEXT',
    'NUMBER': 'FIELD_TYPE_NUMBER',
    'SINGLE_SELECT': 'FIELD_TYPE_SINGLE_SELECT',
    'MULTI_SELECT': 'FIELD_TYPE_MULTI_SELECT',
    'DATE': 'FIELD_TYPE_DATE',
    'DATE_TIME': 'FIELD_TYPE_DATE_TIME',
    'ATTACHMENT': 'FIELD_TYPE_ATTACHMENT',
    'PHONE_NUMBER': 'FIELD_TYPE_PHONE_NUMBER',
    'EMAIL': 'FIELD_TYPE_EMAIL',
    'CHECKBOX': 'FIELD_TYPE_CHECKBOX',
    'PROGRESS': 'FIELD_TYPE_PROGRESS',
    'CURRENCY': 'FIELD_TYPE_CURRENCY',
    'PERCENTAGE': 'FIELD_TYPE_PERCENTAGE',
  };
  return typeMap[type?.toUpperCase()] || 'FIELD_TYPE_TEXT';
}

async function createSmartSheet(schema) {
  const { doc_name, sheets = [], need_dashboard = false, need_gantt = false } = schema;

  log(`[creator] Creating: ${doc_name}, sheets: ${sheets.length}`);

  // 1. 创建智能表格
  const createResult = run('doc create_doc', { doc_name, doc_type: 10 });
  if (createResult.errcode !== 0) {
    throw new Error(`创建文档失败: ${createResult.errmsg}`);
  }

  const docid = createResult.docid;
  const url = createResult.url;
  log(`[creator] Doc: ${docid}, ${url}`);

  // 2. 获取默认子表
  const sheetResult = run('doc smartsheet_get_sheet', { docid });
  if (sheetResult.errcode !== 0) {
    throw new Error(`获取子表失败: ${sheetResult.errmsg}`);
  }

  const sheetList = sheetResult.sheet_list || [];
  if (sheetList.length === 0) {
    throw new Error('未找到子表');
  }

  // 3. 处理每个子表
  for (let i = 0; i < sheets.length; i++) {
    const sheet = sheets[i];
    const { name, fields = [], records = [] } = sheet;

    log(`[creator] Sheet ${i + 1}: ${name}`);

    let sheetId;
    if (i === 0) {
      sheetId = sheetList[0].sheet_id;
      // 重命名子表
      run('doc smartsheet_update_sheet', { docid, sheet_id: sheetId, properties: { title: name } });
    } else {
      // 创建新子表
      const addResult = run('doc smartsheet_add_sheet', { docid, properties: { title: name } });
      if (addResult.errcode !== 0) {
        log(`[creator] Add sheet warning: ${addResult.errmsg}`);
        continue;
      }
      sheetId = addResult.properties?.sheet_id;
      // 重新获取sheet列表找到新子表
      const allSheets = run('doc smartsheet_get_sheet', { docid });
      const newSheet = (allSheets.sheet_list || []).find(s => s.title === name);
      sheetId = newSheet?.sheet_id || sheetId;
    }

    // 4. 获取现有字段
    const fieldsResult = run('doc smartsheet_get_fields', { docid, sheet_id: sheetId });
    const existingFields = fieldsResult.fields || [];
    const firstFieldId = existingFields[0]?.field_id;

    // 5. 添加/修改字段
    if (fields.length > 0) {
      // 重命名第一个字段
      if (firstFieldId) {
        const firstField = fields[0];
        run('doc smartsheet_update_fields', {
          docid, sheet_id: sheetId,
          fields: [{ field_id: firstFieldId, field_title: firstField.title, field_type: mapFieldType(firstField.type) }]
        });
      }

      // 添加剩余字段
      const remaining = fields.slice(1);
      if (remaining.length > 0) {
        const fieldConfigs = remaining.map(f => {
          const config = {
            field_title: f.title,
            field_type: mapFieldType(f.type)
          };
          if (f.options && f.options.length > 0) {
            config.property = { options: f.options.map(opt => ({ text: opt })) };
          }
          return config;
        });
        run('doc smartsheet_add_fields', { docid, sheet_id: sheetId, fields: fieldConfigs });
      }
    }

    // 6. 添加记录
    if (records.length > 0) {
      const recordValues = records.map(rec => {
        const values = {};
        for (const [key, value] of Object.entries(rec)) {
          values[key] = [{ type: 'text', text: String(value) }];
        }
        return { values };
      });

      // 分批添加
      const BATCH = 100;
      for (let j = 0; j < recordValues.length; j += BATCH) {
        const batch = recordValues.slice(j, j + BATCH);
        run('doc smartsheet_add_records', { docid, sheet_id: sheetId, records: batch });
      }
    }

    await sleep(200);
  }

  // 7. 高级功能提示
  const features = [];
  if (need_dashboard) features.push('仪表盘（表格右上角+号→添加视图→仪表盘）');
  if (need_gantt) features.push('甘特图（表格右上角+号→添加视图→甘特图）');

  return {
    success: true,
    docid,
    url,
    features,
    message: features.length > 0
      ? `创建成功！高级功能：${features.join('、')}，请打开链接手动配置。`
      : '创建成功！'
  };
}

// 主入口
async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.log(JSON.stringify({ success: false, error: '请提供JSON方案参数' }));
    process.exit(1);
  }

  try {
    const schema = JSON.parse(args.join(' '));
    const result = await createSmartSheet(schema);
    console.log(JSON.stringify(result));
  } catch (e) {
    console.log(JSON.stringify({ success: false, error: e.message }));
    process.exit(1);
  }
}

main();
