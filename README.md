# 基于 MongoDB 的问卷系统

这是课程大作业第一阶段的可运行实现。系统使用 FastAPI、PyMongo、MongoDB 和简单的 HTML/CSS/JavaScript，覆盖用户账号、问卷管理、四种题型、答案校验、动态跳转、回答保存和自动统计。

## 已实现功能

- 用户注册、登录和退出
- 密码使用 scrypt 加盐哈希保存
- 用户只能管理自己创建的问卷
- 创建、修改、发布和关闭问卷
- 截止时间控制
- 公开问卷链接
- 单选题、多选题、文本填空题、数字填空题
- 必答、选择数量、文本长度、数字范围和整数校验
- 单选、多选、数字条件跳转
- 跳转规则存储在 MongoDB 中，不写死在程序里
- 登录后填写问卷
- 填写者必须登录；匿名回答不保存可展示的填写者身份
- 同一登录用户的重复提交控制
- 回答路径和回答内容保存
- 单选、多选、文本和数字统计
- 自动化领域逻辑测试

## 项目结构

```text
mongodb-survey-system/
├─ app/
│  ├─ main.py              Web 路由与业务流程
│  ├─ domain.py            校验和跳转逻辑
│  ├─ db.py                MongoDB 连接与索引
│  ├─ security.py          密码与匿名去重安全逻辑
│  ├─ stats.py             MongoDB 聚合统计
│  ├─ templates/           HTML 页面
│  └─ static/              CSS 与填写问卷脚本
├─ docs/                   项目完整报告和数据结构示例
├─ tests/                  自动测试
├─ env.example             配置示例
├─ gitignore.txt           Git 忽略规则模板
├─ requirements.txt        Python 依赖
└─ run.py                  启动入口
```

## 运行环境

- Python 3.9 或更高版本
- MongoDB 6.0 或更高版本
- Windows、macOS 或 Linux

## Windows 启动步骤

### 1. 启动 MongoDB

如果 MongoDB 安装在 `D:\mongo`：

```powershell
& "D:\mongo\bin\mongod.exe" --dbpath "D:\mongo\data\db"
```

保持这个终端窗口打开。

### 2. 创建 Python 环境并安装依赖

```powershell
conda create -n survey-system python=3.11 -y
conda activate survey-system
cd mongodb-survey-system
pip install -r requirements.txt
```

也可以使用已有的 Python 环境。

### 3. 创建配置文件

```powershell
Copy-Item -LiteralPath env.example -Destination .env
Copy-Item -LiteralPath gitignore.txt -Destination .gitignore
```

为便于网页上传，模板使用不带前导点的文件名。上面的命令会在本机生成 `.env` 配置和 `.gitignore`；`gitignore.txt` 恢复为 `.gitignore` 后，Git 才会自动应用其中的忽略规则。

开发环境默认连接：

```text
mongodb://localhost:27017
```

提交或部署前，请把 `.env` 中的 `SESSION_SECRET` 换成长随机字符串。

### 4. 启动应用

```powershell
python run.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

健康检查和自动 API 文档：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

## 运行测试

```powershell
python -m pytest -q
```

不依赖浏览器的校验、跳转、循环检测、密码和匿名去重逻辑均有自动测试。完整手工测试步骤见 `docs/项目完整报告.md` 的“测试方案与结果”。

## 演示流程

1. 注册创建者账号。
2. 新建问卷并添加至少三道题。
3. 给第一道题设置跳转到第三题的规则。
4. 发布问卷并复制访问链接。
5. 退出后注册另一个填写者账号。
6. 打开链接并填写、提交。
7. 使用创建者账号登录，查看统计结果。

## 设计说明

- 所有业务数据均保存在 MongoDB，不使用关系数据库。
- 使用 `users`、`surveys`、`responses` 三个集合。
- 题目嵌入问卷，因为题目通常随问卷整体读取且数量有界。
- 回答独立存储，支持大量提交和聚合统计。
- 跳转规则保存在题目文档中，可配置而不是写死。
- 当前版本只允许向后跳转，避免循环；服务端仍会检测异常循环。
- 所有填写者都必须先登录；匿名问卷不保存可展示的填写者身份，只保存基于登录用户生成的不可逆 HMAC 去重键来限制重复填写。

数据库设计、接口说明、运行方法、测试记录和 AI 使用过程均已整理在 `docs/项目完整报告.md`。

## AI 使用与操作记录

完整报告第十章以简表整理各阶段的提示词、AI 建议和采用情况。提示词根据实际开发过程归纳改写，重点说明提问的目标、约束和检查方法；操作与测试结果见报告对应章节。后续内容统一更新完整报告。

