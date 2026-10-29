# 基于 MongoDB 的问卷系统

这是在第一阶段系统上继续实现的需求变更版本，保留原有功能并新增题库、共享、版本历史与恢复、使用位置查询和跨问卷统计。

## 已实现功能

- 注册、登录、用户隔离、匿名回答与重复提交控制
- 问卷创建、发布、关闭、截止时间、四种题型、校验与条件跳转
- 独立保存题目，多个问卷复用指定版本
- 按用户名共享，或允许所有登录用户选用
- 不可变历史版本、父版本链、旧版分支、恢复与独立复制
- 发布后的问卷题目锁定，复制成新草稿后继续修改
- 题库创建、改名、题目加入和移出、删除分类
- 按版本查看使用位置和跨问卷统计，数字题含数值分布
- 第一阶段旧数据自动迁移，不删除旧回答

## 启动

在本项目目录打开终端。保持 MongoDB 已启动，例如：

```powershell
& "D:\mongo\bin\mongod.exe" --dbpath "D:\mongo\data\db"
```

安装依赖并启动应用：

```powershell
python -m pip install -r requirements.txt
python run.py
```

浏览器访问 http://127.0.0.1:8000，登录后顶部可见“题目库”和“管理题库”。

默认连接 mongodb://localhost:27017，数据库 survey_system。需要修改配置时，在尚未创建 .env 的情况下执行：

```powershell
Copy-Item -LiteralPath env.example -Destination .env
Copy-Item -LiteralPath gitignore.txt -Destination .gitignore
```

模板名不带前导点，便于网页上传。gitignore.txt 本身为模板，复制为 .gitignore 后才由 Git 自动使用。已有 .env 时直接编辑原配置，不必重新复制。正式部署应更换 SESSION_SECRET。

## 使用流程

1. 登录后进入“管理题库”，创建分类。
2. 进入“题目库”，保存常用题目；问卷中新建的题目也会进入默认题库。
3. 在题目详情填写共享对象的用户名。
4. 在问卷草稿中从题库选用明确的版本。
5. 点击“基于此版本修改”创建新版本，或恢复历史内容为新版本。
6. 旧问卷保持原快照，新草稿可显式切换版本。
7. 查看版本历史、使用位置及跨问卷统计。

题目作者可查看该题在引用问卷中的匿名汇总；被共享者只能查看自己问卷的回答。不同版本分开统计，避免混合不同题型或单位。

## 演示数据

```powershell
python scripts/seed_phase2_demo.py
```

演示账号：phase2_author / password123，phase2_colleague / password123。数据均标记为演示合成数据，不会清空已有问卷。默认演示包含 v1、v2 和恢复生成的 v3，及三份年龄回答 20、22、24。

## 测试

普通测试：

```powershell
python -m pytest -q
```

启用真实 MongoDB 集成测试：

```powershell
$env:TEST_MONGODB_URI="mongodb://127.0.0.1:27017"
python -m pytest -q
```

未设置 TEST_MONGODB_URI 时集成测试明确跳过。启用时使用独立的 survey_phase2_test_ 临时数据库，结束只删除对应测试数据库，不修改 survey_system。本轮完整执行结果：43 passed。

## 结构与设计

- app/catalog.py：版本、共享、题库、快照、旧数据迁移
- app/catalog_routes.py：第二阶段页面与接口
- app/main.py：第一阶段功能与发布锁定
- app/stats.py：MongoDB 聚合统计
- tests/：基础回归、单元测试及真实数据库集成测试
- scripts/：第一阶段脚本及第二阶段演示数据
- docs/项目完整报告.md：统一报告，含数据库设计、测试与 AI 使用记录
- docs/SCHEMA_EXAMPLES.json：六个集合的结构示例

题目系列和版本独立保存，问卷嵌入固定版本快照。发布后添加、删除、跳转修改和切换版本都会被服务端拒绝；恢复旧版生成新记录。第一次启动会为第一阶段题目补充版本来源，原题号和回答不变。

应用接口文档：http://127.0.0.1:8000/docs

## 第二阶段提交

将本阶段修改后的代码、测试用例、README 和 docs 更新到第一阶段的 GitHub 仓库，继续使用“当代数据库管理”分支。

水杉提交项目完成报告 PDF，仓库链接放在报告最前面，文件名为 2026_ECNU_PJ1_2_胡天皓.pdf。

提交截止时间：2026 年 10 月 30 日 00:00（北京时间）。

