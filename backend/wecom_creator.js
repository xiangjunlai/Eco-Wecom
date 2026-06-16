#!/usr/bin/env node
/**
 * 企业微信智能表格创建工具
 * 通过 wecom-cli 创建完整的智能表格
 *
 * 用法: node wecom_creator.js '<json方案>'
 *
 * 示例:
 * node wecom_creator.js '{
 *   "doc_name": "测试表格",
 *   "sheets": [
 *     {
 *       "name": "客户信息",
 *       "fields": [
 *         {"title": "客户名称", "type": "TEXT"},
 *         {"title": "行业", "type": "SINGLE_SELECT", "options": ["金融", "制造"]}
 *       ],
 *       "records": [
 *         {"客户名称": "ABC公司", "行业": "金融"}
 *       ]
 *     }
 *   ],
 *   "need_dashboard": false,
 *   "need_gantt": false
 * }'
 */

import { execSync, exec } from 'node:child_process';
import { parseArgs } from 'node:util';

const log = console.error;

function runWecom(args) {
  // 构建命令 - wecom-cli 使用 --json 参数
  // 格式: wecom-cli <category> <command> --json '<json>'
  const cmdParts = args.join(' ').split(" --json ");
  let cmd;
  if (cmdParts.length === 2) {
    // 有 --json 参数
    cmd = `wecom-cli ${cmdParts[0]} --json '${cmdParts[1]}'`;
  } else {
    cmd = `wecom-cli ${args.join(' ')}`;
  }
  log(`[wecom] ${cmd}`);

  try {
    const output = execSync(cmd, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
    return output;
  } catch (e) {
    log(`[wecom] Error: ${e.message}`);
    throw e;
  }
}

function parseWecomResult(stdout) {
  // wecom-cli 返回的是嵌套JSON: {"id":"...","result":{"content":[{"text":"{...}","type":"text"}]}}
  try {
    const outer = JSON.parse(stdout);
    const content = outer?.result?.content?.[0]?.text;
    return content ? JSON.parse(content) : { errcode: -1, errmsg: 'empty result' };
  } catch (e) {
    log(`[wecom] Parse error: ${e.message}, stdout: ${stdout}`);
    return { errcode: -1, errmsg: 'parse error' };
  }
}

function runWecomParse(args) {
  const result = runWecom(args);
  return parseWecomResult(result.stdout || result);
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function createSmartSheet(schema) {
  const { doc_name, sheets = [], need_dashboard = false, need_gantt = false } = schema;

  log(`[creator] Creating smartsheet: ${doc_name}`);
  log(`[creator] Sheets: ${sheets.length}, need_dashboard: ${need_dashboard}, need_gantt: ${need_gantt}`);

  // 1. 创建智能表格
  log('[creator] Step 1: Create doc');
  const createResult = runWecomParse([
    'doc', 'create_doc',
    JSON.stringify({ doc_name, doc_type: 10 })
  ]);

  if (createResult.errcode !== 0) {
    throw new Error(`创建文档失败: ${createResult.errmsg}`);
  }

  const docid = createResult.docid;
  const url = createResult.url;
  log(`[creator] Doc created: ${docid}, ${url}`);

  // 2. 获取默认子表
  log('[creator] Step 2: Get default sheet');
  const sheetResult = runWecomParse([
    'doc', 'smartsheet_get_sheet',
    JSON.stringify({ docid })
  ]);

  if (sheetResult.errcode !== 0) {
    throw new Error(`获取子表失败: ${sheetResult.errmsg}`);
  }

  const sheetList = sheetResult.sheet_list || [];
  if (sheetList.length === 0) {
    throw new Error('未找到子表');
  }

  // 记录已处理的子表
  const processedSheets = new Set();

  // 3. 处理每个子表
  for (let i = 0; i < sheets.length; i++) {
    const sheet = sheets[i];
    const { name, fields = [], records = [] } = sheet;

    log(`[creator] Processing sheet ${i + 1}: ${name}`);

    // 获取或创建子表
    let sheetId;
    if (i === 0) {
      // 第一个子表使用默认子表
      sheetId = sheetList[0].sheet_id;
      log(`[creator] Using default sheet: ${sheetId}`);

      // 重命名子表
      runWecomParse([
        'doc', 'smartsheet_update_sheet',
        JSON.stringify({ docid, sheet_id: sheetId, properties: { title: name } })
      ]);
    } else {
      // 创建新子表
      const addSheetResult = runWecomParse([
        'doc', 'smartsheet_add_sheet',
        JSON.stringify({ docid, properties: { title: name } })
      ]);

      if (addSheetResult.errcode !== 0) {
        log(`[creator] Add sheet warning: ${addSheetResult.errmsg}`);
        continue;
      }

      sheetId = addSheetResult.properties?.sheet_id;
      log(`[creator] New sheet created: ${sheetId}`);
    }

    processedSheets.add(sheetId);

    // 4. 获取现有字段
    log(`[creator] Get fields for sheet: ${sheetId}`);
    const fieldsResult = runWecomParse([
      'doc', 'smartsheet_get_fields',
      JSON.stringify({ docid, sheet_id: sheetId })
    ]);

    const existingFields = fieldsResult.fields || [];
    const firstFieldId = existingFields[0]?.field_id;

    // 5. 处理字段
    if (fields.length > 0) {
      // 重命名第一个字段
      if (firstFieldId) {
        const firstField = fields[0];
        runWecomParse([
          'doc', 'smartsheet_update_fields',
          JSON.stringify({
            docid,
            sheet_id: sheetId,
            fields: [{
              field_id: firstFieldId,
              field_title: firstField.title,
              field_type: mapFieldType(firstField.type)
            }]
          })
        ]);
        log(`[creator] Renamed first field to: ${firstField.title}`);
      }

      // 添加剩余字段
      const remainingFields = fields.slice(1);
      if (remainingFields.length > 0) {
        const fieldConfigs = remainingFields.map(f => ({
          field_title: f.title,
          field_type: mapFieldType(f.type),
          ...(f.options && f.options.length > 0 ? {
            property: {
              options: f.options.map(opt => ({ text: opt }))
            }
          } : {})
        }));

        runWecomParse([
          'doc', 'smartsheet_add_fields',
          JSON.stringify({ docid, sheet_id: sheetId, fields: fieldConfigs })
        ]);
        log(`[creator] Added ${remainingFields.length} fields`);
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

      // 分批添加记录（每批最多100条）
      const BATCH_SIZE = 100;
      for (let j = 0; j < recordValues.length; j += BATCH_SIZE) {
        const batch = recordValues.slice(j, j + BATCH_SIZE);
        runWecomParse([
          'doc', 'smartsheet_add_records',
          JSON.stringify({ docid, sheet_id: sheetId, records: batch })
        ]);
        log(`[creator] Added records ${j + 1} to ${j + batch.length}`);
      }
    }

    // 短暂延迟避免频率限制
    await sleep(200);
  }

  // 7. 检查高级功能
  const features = [];
  if (need_dashboard) {
    features.push('仪表盘（请在表格中手动配置：点击右上角+号→添加视图→仪表盘）');
  }
  if (need_gantt) {
    features.push('甘特图（请在表格中手动配置：点击右上角+号→添加视图→甘特图）');
  }

  return {
    success: true,
    docid,
    url,
    features,
    message: features.length > 0
      ? `智能表格创建成功！高级功能提示：${features.join('、')}。请打开链接进行配置。`
      : '智能表格创建成功！'
  };
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
    'LINK': 'FIELD_TYPE_LINK',
    'USER': 'FIELD_TYPE_USER',
    'PHONE': 'FIELD_TYPE_PHONE_NUMBER',
    'EMAIL': 'FIELD_TYPE_EMAIL',
    'CHECKBOX': 'FIELD_TYPE_CHECKBOX',
    'PROGRESS': 'FIELD_TYPE_PROGRESS',
    'CURRENCY': 'FIELD_TYPE_CURRENCY',
    'PERCENTAGE': 'FIELD_TYPE_PERCENTAGE',
    'LOCATION': 'FIELD_TYPE_LOCATION',
    'IMAGE': 'FIELD_TYPE_IMAGE',
    'FORMULA': 'FIELD_TYPE_FORMULA',
    'AUTO_NUMBER': 'FIELD_TYPE_AUTO_NUMBER',
    'GROUP_MEMO': 'FIELD_TYPE_GROUP_MEMO',
  };
  return typeMap[type.toUpperCase()] || 'FIELD_TYPE_TEXT';
}

// 主入口
async function main() {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.log(JSON.stringify({
      success: false,
      error: '请提供JSON方案参数'
    }));
    process.exit(1);
  }

  try {
    const schema = JSON.parse(args.join(' '));
    const result = await createSmartSheet(schema);
    console.log(JSON.stringify(result));
  } catch (e) {
    console.log(JSON.stringify({
      success: false,
      error: e.message
    }));
    process.exit(1);
  }
}

main();
