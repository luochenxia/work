# 基于 MongoDB 的问卷系统

本项目是一个基于 MongoDB 的问卷系统。第二阶段在原有问卷功能上，增加了题库、题目共享、版本管理和跨问卷统计。

## 主要功能

- 用户注册和登录，填写问卷前也需要登录
- 创建、发布和关闭问卷，设置截止时间、匿名填写和是否允许重复提交
- 单选、多选、文本填空和数字填空，支持答案校验和条件跳转
- 保存常用题目，加入题库，并在不同问卷中使用
- 将题目共享给其他用户，或开放给所有登录用户使用
- 修改题目时保存新版本，查看历史版本和恢复旧内容
- 查看题目用在哪些问卷中，统计同一版本在不同问卷中的回答
- 保留第一阶段已有的问卷和回答，启动时补充题目的版本信息

## 启动

先启动 MongoDB，下面的路径按本机安装位置修改：

```powershell
& "D:\mongo\bin\mongod.exe" --dbpath "D:\mongo\data\db"
```

然后在项目目录中安装依赖并启动：

```powershell
python -m pip install -r requirements.txt
python run.py
```

浏览器访问 http://127.0.0.1:8000，注册或登录后即可使用。

默认连接为 mongodb://localhost:27017，数据库名为 survey_system。首次配置时，可以复制模板：

```powershell
Copy-Item -LiteralPath env.example -Destination .env
Copy-Item -LiteralPath gitignore.txt -Destination .gitignore
```

MongoDB 地址和 SESSION_SECRET 在 .env 中设置。已有 .env 时直接修改该文件。gitignore.txt 是 Git 忽略规则的模板，复制为 .gitignore 后生效。

## 使用流程

1. 登录后进入“管理题库”，创建分类。
2. 进入“题目库”，保存常用题目；问卷中新建的题目也会进入默认题库。
3. 在题目详情填写共享对象的用户名。
4. 在问卷草稿中从题库选题，并选择需要的版本。
5. 点击“基于此版本修改”创建新版本，或恢复历史内容为新版本。
6. 已发布问卷保留原来的题目内容，草稿中可以手动切换版本。
7. 查看版本历史、使用位置及跨问卷统计。

题目作者可以查看该题的跨问卷统计，收到共享的用户只能查看自己问卷中的回答。统计按版本分别计算，例如“年龄（周岁）”和“年龄（月）”不会放在一起算平均值。

## 演示数据

```powershell
python scripts/seed_phase2_demo.py
```

演示账号为 phase2_author 和 phase2_colleague，密码均为 password123。演示中包含题目共享、v1 和 v2 两个版本，以及恢复旧内容后生成的 v3。三份年龄回答分别为 20、22、24，平均值为 22。演示数据由脚本生成，不会清空已有问卷。

## 测试

运行单元测试：

```powershell
python -m pytest -q
```

需要检查数据库相关功能时，先启动 MongoDB，再运行：

```powershell
$env:TEST_MONGODB_URI="mongodb://127.0.0.1:27017"
python -m pytest -q
```

设置 TEST_MONGODB_URI 后会一起运行集成测试，否则跳过这部分测试。集成测试使用 survey_phase2_test_ 开头的临时数据库，结束后自动清理，不修改应用使用的 survey_system。完整测试结果为 43 passed。

## 结构与设计

- app/catalog.py：版本、共享、题库、快照、旧数据迁移
- app/catalog_routes.py：第二阶段页面与接口
- app/main.py：第一阶段功能与发布锁定
- app/stats.py：MongoDB 聚合统计
- tests/：基础回归、单元测试及真实数据库集成测试
- scripts/：第一阶段脚本及第二阶段演示数据
- docs/项目完整报告.md：项目报告，包含数据库设计、测试结果和 AI 使用记录
- docs/SCHEMA_EXAMPLES.json：六个集合的结构示例

题目及其版本单独保存，问卷中保存选定版本的内容副本。这样修改题目后，已经发布的问卷仍使用原来的内容。发布后的问卷不能直接改题，需要先复制成草稿。恢复旧版本也会生成一条新记录，原有历史继续保留。

应用接口文档：http://127.0.0.1:8000/docs

