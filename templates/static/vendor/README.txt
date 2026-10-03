第三方前端库清单（vendor）
============================================================

这些是第三方库的原样副本，请勿手工修改内容。
升级时用官方版本替换本目录文件，并同步更新 dashboard.html / login.html
头部的 CDN 兜底地址与版本注释。

版本与来源
------------------------------------------------------------
下载源：https://s4.zstatic.net/npm/  （与页面里的 CDN 兜底地址同源）

  bootstrap.min.css               Bootstrap 5.3.0    bootstrap@5.3.0/dist/css/bootstrap.min.css
  bootstrap.bundle.min.js         Bootstrap 5.3.0    bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js
  jquery.min.js                   jQuery 3.6.0       jquery@3.6.0/dist/jquery.min.js
  summernote-lite.min.css         Summernote 0.8.18  summernote@0.8.18/dist/summernote-lite.min.css
  summernote-lite.min.js          Summernote 0.8.18  summernote@0.8.18/dist/summernote-lite.min.js
  summernote-zh-CN.min.js         Summernote 0.8.18  summernote@0.8.18/dist/lang/summernote-zh-CN.min.js
  font/summernote.{eot,woff2,woff,ttf}
                                  Summernote 0.8.18  图标字体，被 summernote-lite.min.css
                                                     以相对路径 font/ 引用（不可删）

大小与 SHA256（取前 16 位，用于快速核对是否为上游原版）
------------------------------------------------------------
  bootstrap.min.css               232914   7f1d37f0d90b6385
  bootstrap.bundle.min.js          80421   aa53d582f97eb594
  jquery.min.js                    89501   ff1523fb7389539c
  summernote-lite.min.css          30447   a00e83ff2222d08f
  summernote-lite.min.js          163197   e4de051e54bb6d6c
  summernote-zh-CN.min.js           4394   c1ea237b775f9967
  font/summernote.eot              12072   e0e54acda6f6686e
  font/summernote.woff2             6156   6ae62bbeee031333
  font/summernote.woff              7428   ad20bd13f091371e
  font/summernote.ttf              11896   bc06998a0259b2a4

为什么要放在这里
------------------------------------------------------------
面板原先完全依赖外部 CDN（s4.zstatic.net）。CDN 不可达时脚本整批加载失败，
而 dashboard.js 的第一句就是 summernote 初始化，会导致面板所有按钮失效、
且不报任何错误。现在改为：

  本地直连（127.0.0.1 / localhost / 局域网）→ 读本目录文件，断网可用
  远程中继（经 SiverPanel，请求头带 X-Siver-Remote）→ 优先走 CDN，避免大文件过中继
  两者互为兜底，任一源不可用都能正常打开面板

判断与兜底逻辑写在 dashboard.html / login.html 头部，改这里之前请先读那段注释。

注意事项
------------------------------------------------------------
1. 这些文件保留上游原始字节（未做任何裁剪），因此仍带 sourceMappingURL 注释。
   对应的 .map 文件未随包分发，只有打开浏览器开发者工具时才会看到 404，属预期现象。
2. summernote-lite.min.css 用相对路径 font/ 引用图标字体，font/ 目录必须一起保留，
   否则富文本编辑器的工具栏图标会缺失。
3. 打包由 SiverWXbot.spec 的 ('templates','templates') 整目录递归带入，无需额外配置。
