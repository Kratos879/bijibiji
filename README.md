# 哔记 BijiBiji

哔记是一个本地优先的 B 站视频转录与课程笔记工具。粘贴视频链接后，它会优先读取 B 站字幕；没有可用字幕时，可使用豆包录音文件识别 2.0 或 OpenAI 兼容语音服务。笔记和画面分析使用你配置的模型 API。

## 下载源码

[下载完整源码压缩包](./哔记-BijiBiji-源码.zip)。解压后进入 `bijibiji` 目录。压缩包不包含本机数据库、Cookie、API Key、视频缓存和媒体工具二进制。

## 本地运行

需要 Python 3.11+、FFmpeg 和 ffprobe。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

打开 http://127.0.0.1:8766 ，在「模型与配置」中填写模型服务凭证。豆包语音 2.0 的 API Key 需从豆包语音控制台获取；方舟聊天模型 Key 不能代替语音 Key。

## 功能

- B 站视频链接、稍后再看及分享链接解析
- 优先使用字幕，缺失时可回退到语音识别
- 可选视频截图分析，也可只处理音频
- 课程讲义、实操教程、学术报告、复习提纲、自测学习模板
- Markdown 笔记、段落转写、课程检索与按需问答
- 本地历史记录、导出与多主题界面

## 数据与部署

API Key、Cookie、视频及处理缓存默认保存在本机 `data/`。不要把该目录提交到版本库。远程部署必须配置强随机 `KEJING_ACCESS_TOKEN` 并使用 HTTPS 反向代理；不要将无访问口令的服务暴露到公网。

项目测试：

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
```
# bijibiji
哔记 BijiBiji — B站视频字幕与课程笔记生成工具
