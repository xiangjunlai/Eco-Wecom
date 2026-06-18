# Findings - 知识库重构

## 后端 API 设计

### POST /api/kb/upload
- 接收: `category` (Form) + `file` (UploadFile)
- 处理: 提取文本 → 存磁盘 → AI生成对比案例
- 返回: `{id, filename, char_count, category, contrast: {title, question, default, enhanced}, date}`

### GET /api/kb/files
- 返回: `[{id, filename, size, date}]`

### DELETE /api/kb/files/{file_id}
- 返回: `{success: true}`

## 字段映射问题

### 问题: undefined 显示
后端 contrast 返回: `{title, question, default, enhanced}`
前端期望: `{question, default, defaultText, enhanced, kbText}`

**修复**: 前端做兼容处理
```javascript
var q = c.question || c.title || '示例问题';
var d = c.default || c.defaultText || '';
var e = c.enhanced || c.kbText || '';
```

## CSS 冲突

### 问题: 完善度进度条和文件列表进度条共用 `.kb-progress-wrap`
- 完善度进度条应该是灵活的
- 文件列表进度条固定80px

**修复**: 分离CSS类
- `.kb-header-progress` - 完善度用
- `.kb-file-progress` - 文件列表用

## 文件存储路径
```
backend/data/kb/{user_id}/{uuid}_{filename}
```
