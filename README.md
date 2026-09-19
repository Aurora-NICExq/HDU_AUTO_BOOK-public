![logo](./docs/logo.png)
# HDU Auto Book 杭州电子科技大学图书馆自动预约脚本

当前请按本文配置和运行。原作者 README 原文见 [`README.original.md`](./README.original.md)。

## 它做什么

每天 **19:57**、**20:57**（上海时区）自动跑：

1. 用学校统一身份认证（CAS）登录图书馆
2. 先查是否**已经有预约**；有则立刻结束，不再提交
3. 没有预约时，提交一单：**后天 7:00–22:00**，默认在二楼西随机抽座
4. 抽到已占用的座位会换一个再试（最多 20 次）
5. 接口说已有预约 / 不能重复预约时结束，不再连打

20:57 是 19:57 没跑成或没约上时的补跑。第一次已经约上，第二次查到已有预约就会退出。

不要反复手动点运行。容易被图书馆限制账号。

## 1. Fork 本仓库

Fork 到你自己的 GitHub 账号。

## 2. 填写登录凭据

仓库 **Settings → Secrets and variables → Actions → New repository secret**：

| 名称 | 填什么 |
|---|---|
| `SCHOOL_ID` | 学号 |
| `PASSWORD` | 学校统一身份认证密码（信息门户密码） |
| `SCKEY` | 选填。 [Server酱](https://sct.ftqq.com/) 推送 key |

## 3. 选座位和时段

编辑 `user_config.yml`：

- 默认七天都约后天 **7:00–22:00**，区域 **二楼西**
- 换楼层：改对应星期的 `name`，可选名称见 `config/seat_config.yml`（短名和全称都行）
- 指定座位：`name` 改成 `自定义`，在文件底部 `自定义` 列表填座位号

改完后 Commit。

## 4. 打开 Actions

打开仓库 **Actions**，启用 workflows。之后按上面的时间自动跑。也可以在 Actions 里手动 **Run workflow**（同样会先检查已有预约）。

GitHub 的定时任务不能保证整分准时。

## 5. 需要的环境变量（本地跑）

```bash
export SCHOOL_ID='学号'
export PASSWORD='信息门户密码'
python main.py
```

本地也不要连续多次跑。
