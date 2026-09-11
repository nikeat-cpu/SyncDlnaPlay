/* =========================================================================
   SyncDlnaPlay · i18n（界面中英双语）
   -------------------------------------------------------------------------
   设计：不改动业务代码，用「渲染后文本替换」实现本地化。
     · 中文模式：完全空转，零开销。
     · 英文模式：MutationObserver 监听 DOM，把归一化后能精确命中的中文文本
       替换为英文；动态文案（如「3 台设备」「第 2 页 · 30 首」）由 RX 规则处理。
   切换语言直接 location.reload()，避免反向翻译的歧义。
   ========================================================================= */
(function (w, d) {
  'use strict';

  var KEY = 'dlna_lang';
  var cur = 'zh';

  /* ---------- 精确匹配词典（键 = 归一化后的中文原文） ---------- */
  var EN = {
    /* —— 底栏 / 页面标题 —— */
    "正在播放": "Now Playing",
    "我的设备": "My Devices",
    "本地曲库": "Local Library",
    "在线搜索": "Online Search",
    "播放列表": "Queue",
    "📡 我的设备": "📡 Devices",
    "💽 本地曲库": "💽 Local",
    "🌐 在线搜索": "🌐 Online",
    "📋 播放列表": "📋 Queue",
    "▶ 正在播放": "▶ Now Playing",

    /* —— 通用按钮 —— */
    "搜索": "Search",
    "关闭": "Close",
    "取消": "Cancel",
    "确定": "OK",
    "完成": "Done",
    "添加": "Add",
    "清空": "Clear",
    "刷新": "Refresh",
    "重扫": "Rescan",
    "重置": "Reset",
    "说明": "Description",
    "标题": "Title",
    "密码": "Password",
    "未知": "Unknown",
    "未知错误": "Unknown error",
    "未知原因": "Unknown reason",
    "加载歌词…": "Loading lyrics…",
    "暂无歌词": "No lyrics",
    "失败": "Failed",
    "已完成": "Done",
    "排队中": "Queued",
    "下载中": "Downloading",
    "已跳过": "Skipped",
    "已更新": "Updated",
    "已删除": "Deleted",
    "已校准": "Calibrated",
    "已清空": "Cleared",
    "已移除": "Removed",
    "已添加": "Added",
    "已复制": "Copied",
    "已切换": "Switched",
    "已切换播放模式": "Play mode changed",
    "已开始播放": "Playback started",
    "已开始重新扫描": "Rescan started",
    "已恢复默认下载目录": "Download folder reset to default",
    "已获得读取权限，开始扫描音乐": "Permission granted — scanning your music",
    "已添加，正在扫描…": "Added, scanning…",
    "已添加，正在挂载…": "Added, mounting…",
    "播放失败": "Playback failed",
    "播放列表已播完": "Queue finished",
    "播放列表是空的": "The queue is empty",
    "该曲目没有可用的播放地址": "This track has no playable URL",
    "未发现可用音响，已改用手机本机播放": "No speaker available — playing on this phone",
    "开始下载": "Starting download",
    "上一个下载请求还在处理中…": "A previous download is still running…",
    "下载并解析中…": "Downloading & resolving…",
    "正在解析下载地址…": "Resolving download URL…",
    "正在准备播放…": "Preparing playback…",
    "正在推送到音响…": "Casting to speaker…",
    "正在校准…": "Calibrating…",
    "正在扫描…": "Scanning…",
    "正在扫描音乐目录…": "Scanning music folders…",
    "正在扫描局域网，约 5～15 秒…": "Scanning LAN, about 5–15 s…",
    "正在挂载…": "Mounting…",
    "正在卸载…": "Unmounting…",
    "正在启动…": "Starting…",
    "启动失败": "Startup failed",
    "读取…": "Loading…",
    "读取中…": "Loading…",
    "读取设备…": "Reading devices…",
    "读取文件…": "Reading file…",
    "读取失败": "Read failed",
    "解析中…": "Resolving…",
    "搜索中…": "Searching…",
    "测试中…": "Testing…",
    "测试连接": "Test connection",
    "添加中…": "Adding…",
    "挂载": "Mount",
    "卸载": "Uninstall",
    "启用": "Enable",
    "停用": "Disable",
    "开": "On",
    "关": "Off",
    "本地": "Local",
    "本机播放": "This phone",
    "音响": "Speaker",
    "重复": "Repeat",

    /* —— 音量面板 —— */
    "音量": "Volume",
    "音量 · 手机本机": "Volume · This phone",
    "快速调整": "Quick set",
    "拖动滑条或点 − / + 调节音量，长按 − / + 可连续调节。":
      "Drag the slider, or tap − / + . Long-press − / + for continuous change.",
    "这是手机自己的媒体音量，只影响「手机本机」播放。":
      "This is the phone's own media volume — it only affects “This phone” playback.",
    "输出方式": "Output",
    "输出方式：": "Output:",
    "输出：手机本机": "Output: This phone",
    "输出：音响": "Output: Speaker",
    "🔊 音响播放": "🔊 Speaker",
    "📱 手机本机": "📱 This phone",
    "🔊 音响播放」把声音投到选中的 DLNA 音响；「📱 手机本机」用手机扬声器/耳机放。切换时另一边会自动停。":
      "“🔊 Speaker” casts to the selected DLNA speakers; “📱 This phone” plays through the phone's speaker or headphones. Switching stops the other side automatically.",
    "切「手机本机」＝声音从手机出，音响自动停。":
      "Switch to “This phone” — audio comes from the phone and the speaker stops automatically.",

    /* —— 设备页 —— */
    "选择音响": "Select speaker",
    "还没发现音响": "No speakers found yet",
    "先选一台音响": "Select a speaker first",
    "可同时勾选多台，组成同步播放组。": "Tick several speakers to form a sync group.",
    "同步播放时会一起设置所有已选音响。": "Volume applies to every speaker in the sync group.",
    "提示：先点一台音响把它选上，再回「曲库」或「在线」点歌播放。选中多台可以多房间同步播放。":
      "Tip: tick a speaker first, then go back to Library or Online and tap a song. Select several speakers for multi-room playback.",
    "扫描不到音响？": "Can't find your speaker?",
    "确认手机和音响在同一 Wi-Fi；部分路由器开了 AP 隔离会屏蔽发现协议。找不到也没关系，会自动用手机本机播放。":
      "Make sure the phone and the speaker are on the same Wi-Fi. Some routers block discovery with AP isolation. If nothing is found, playback automatically falls back to this phone.",
    "确认音响已开机、和手机在同一个 WiFi，然后点「重新扫描」":
      "Check that the speaker is powered on and on the same Wi-Fi as your phone, then tap Rescan.",
    "多选：": "Multi-select:",
    "多房间同步微调": "Multi-room sync tuning",
    "两台以上音响同时播放时，声音会有一前一后。给先出声那台加一点延迟就能对齐；点「设备」页的「同步校准」可以自动测。":
      "With two or more speakers the sound may drift apart. Add a little delay to the one that starts early to line them up; tap Sync calibration on the Devices page to measure automatically.",
    "自动发现局域网里的 DLNA/UPnP 音响（斐讯音箱、小爱、电视等）。":
      "Automatically discovers DLNA/UPnP renderers on your LAN (smart speakers, TVs, AV receivers…).",
    "扫描局域网": "Scan LAN",
    "扫描：": "Scan:",
    "上次扫描：": "Last scan:",
    "重新扫描": "Rescan",
    "退出应用": "Quit app",
    "重新启动": "Restart",
    "完全运行在手机上": "Runs entirely on your phone",
    "独立运行版：DLNA 控制、曲库扫描、在线音源全部在手机本机运行，不依赖家中服务器，换任何网络都能用。":
      "Standalone: DLNA control, library scanning and online sources all run on your phone. No home server required — it works on any network.",

    /* —— 曲库 —— */
    "搜索曲库": "Search library",
    "🔍 搜索曲库": "🔍 Search library",
    "搜索歌曲 / 歌手": "Search songs / artists",
    "歌曲名 / 专辑名": "Song / album title",
    "请输入歌名或歌手": "Enter a song or artist name",
    "曲库工具": "Library tools",
    "曲库管理": "Library Manager",
    "🗂 曲库管理": "🗂 Library Manager",
    "🗂 音乐目录管理": "🗂 Music folder manager",
    "音乐目录": "Music folders",
    "更多": "More",
    "＋ 当前目录全部入列表": "＋ Add whole folder",
    "▶ 播放当前目录全部": "▶ Play whole folder",
    "播放整个文件夹": "Play whole folder",
    "↑ 上一级": "↑ Up",
    "当前目录：": "Current folder:",
    "这个目录是空的": "This folder is empty",
    "目录太大，仅索引了前一部分曲目。": "Folder too large — only the first tracks were indexed.",
    "曲目数：": "Tracks:",
    "上次扫描：—": "Last scan: —",
    "本机曲库": "Phone library",
    "本机音乐": "This device",
    "🏠 本机音乐": "🏠 This device",
    "媒体库": "Media Server",
    "「媒体库」= 局域网里的 DLNA 媒体服务器（如 MiniDLNA）。":
      "“Media Server” = a DLNA media server on your LAN (e.g. MiniDLNA).",
    "「本机音乐」= 服务端配置的音乐目录（可在「音乐目录管理」里加本地文件夹或 SMB 共享）。":
      "“This device” = music folders configured on the server (add local folders or SMB shares in Music folder manager).",
    "「本地曲库」放手机里的歌；「在线搜索」搜网上的歌，点 ＋ 加入播放列表。":
      "“Local Library” holds the music on your phone; “Online Search” finds songs on the internet — tap ＋ to add them to the queue.",
    "搜索失败：": "Search failed: ",
    "没找到「": "Nothing found for “",
    "没有结果": "No results",
    "可以回上一页，或换个音源试试": "Go back a page, or try another source",
    "上一页": "Prev",
    "下一页": "Next",
    "‹ 上一页": "‹ Prev",
    "下一页 ›": "Next ›",
    "加入列表": "Add to queue",
    "手机播放": "Play on phone",
    "播放本目录全部": "Play whole folder",
    "重扫": "Rescan",

    /* —— 在线音源 —— */
    "音源": "Sources",
    "音源管理": "Source manager",
    "音源管理：": "Source manager:",
    "添加音源": "Add source",
    "添加音源」": "Add source",
    "已安装的音源（": "Installed sources (",
    "内置": "Built-in",
    "自建": "Custom",
    "[内置]": "[Built-in]",
    "★默认": "★ Default",
    "设为默认": "Set as default",
    "已停用": "Disabled",
    "随 App 内置": "Bundled with app",
    "还没有音源": "No sources yet",
    "默认音源：": "Default source:",
    "记住上次音源：": "Remember last source:",
    "每次搜索会记住所用音源，下次打开自动就是它。":
      "The last source you searched with is remembered and used automatically next time.",
    "在音源管理里点 ★ 星标设为默认。": "Tap the ★ star in Source manager to set it as default.",
    "内置多个 MusicFree 社区音源（元力系列等），支持关键词搜索与翻页。":
      "Several community MusicFree sources are bundled — keyword search and paging supported.",
    "音源就是 MusicFree 的插件。本机自带的几个只是默认值，你可以停用不想要的，也可以自己添加 —— 插件网址、分享码、订阅文件都行。":
      "Sources are MusicFree plugins. The bundled ones are just defaults — disable the ones you don't want, or add your own: plugin URL, share code or subscription file.",
    "MusicFree 插件是社区维护的 .js 文件，常见于插件订阅链接或别人分享的分享码。":
      "MusicFree plugins are community-maintained .js files, usually shared as subscription links or share codes.",
    "支持 MusicFree 插件的各种分发形式：插件源码网址、订阅链接、分享码（一大串字符）、手机里的 .js / .json 文件。":
      "Every common MusicFree distribution format is supported: plugin source URL, subscription link, share code (a long string), or a local .js / .json file.",
    "从网址安装": "Install from URL",
    "从文件导入 .js": "Import a .js file",
    "粘贴插件链接 URL": "Paste plugin URL",
    "粘贴插件源码/分享码": "Paste plugin source / share code",
    "插件 / 订阅网址，http 开头": "Plugin / subscription URL (starts with http)",
    "插件源码 / 分享码 / 订阅 JSON，直接粘进来": "Plugin source / share code / subscription JSON — paste it here",
    "安装粘贴的内容": "Install pasted content",
    "选择本机文件": "Choose a local file",
    "或直接粘贴": "Or paste directly",
    "名称（可留空）": "Name (optional)",
    "先把内容粘到上面的框里": "Paste the content into the box above first",
    "请先填插件或订阅的网址": "Enter the plugin or subscription URL first",
    "安装后会立刻出现在在线音乐的「音源」下拉里。":
      "Once installed it shows up immediately in the Sources dropdown under Online Search.",
    "点搜索框旁的管理入口 → 可「停用/启用」内置音源，也能添加自己的音源：":
      "Tap the manager next to the search box to enable/disable bundled sources, or add your own:",
    "已安装的音源（5）": "Installed sources (5)",
    "第三方音源接口偶尔不稳定，换个音源或稍后再试。":
      "Third-party source APIs are occasionally flaky — switch sources or try again later.",
    "在线歌解析失败 / 下载失败？": "Online song won't resolve or download?",
    "在线歌词取决于音源是否提供；本地歌请在同目录放同名 .lrc 文件（支持 UTF-8/GBK）。":
      "Online lyrics depend on the source. For local songs, put a matching .lrc file next to the audio (UTF-8 or GBK).",
    "（插件运行时未加载）": "(plugin runtime not loaded)",
    "（音源不可用）": "(source unavailable)",
    "（没有启用的音源，去「音源」里加一个）": "(no source enabled — add one in Sources)",
    "插件运行时未加载": "Plugin runtime not loaded",
    "插件运行时未加载，无法搜索": "Plugin runtime not loaded — cannot search",
    "载入插件失败": "Failed to load plugins",
    "安装失败：": "Install failed: ",
    "没能装上：": "Could not install: ",
    "部分音源出错:": "Some sources failed: ",
    "插件加载失败:": "Plugin load failed: ",
    "全选": "Select all",

    /* —— 播放列表 —— */
    "播放模式（v2.8 起在这里设置）：": "Play mode (set here since v2.8):",
    "🔀 随机": "🔀 Shuffle",
    "🔁 列表循环": "🔁 Repeat all",
    "🔂 单曲循环": "🔂 Repeat one",
    "➡ 顺序播放": "➡ In order",
    "🔀 随机、🔁 列表循环、🔂 单曲循环、➡ 顺序播放。":
      "🔀 Shuffle, 🔁 Repeat all, 🔂 Repeat one, ➡ In order.",
    "在「曲库」或「在线」里点 ＋ 加歌": "Tap ＋ in Library or Online to add songs",
    "在「播放列表」点歌即播。声音从哪出由「正在播放」页的「输出方式」决定：音响 or 手机。":
      "Tap a song in the queue to play it. Where the sound comes out is set by Output on the Now Playing page: speaker or phone.",
    "· 点歌曲行任意位置即跳播；右侧 × 可从列表移除；「清空」一键清空。":
      "· Tap anywhere on a row to jump to that song; the × on the right removes it; Clear empties the queue.",

    /* —— 正在播放 / 歌词 —— */
    "封面 / 歌词：": "Cover / Lyrics:",
    "有歌词时封面位置直接显示滚动歌词，点任意一句可跳转到那句；没有歌词时显示唱片封面。":
      "When lyrics are available they replace the cover and scroll with the song — tap a line to jump there. Without lyrics, the album art is shown.",
    "歌词": "Lyrics",
    "无偏移": "No offset",
    "歌词无偏移": "Lyrics: no offset",
    "快 0.5s": "Faster 0.5s",
    "慢 0.5s": "Slower 0.5s",
    "进度条：": "Progress bar:",
    "可拖动；投音响时进度按本机时钟平滑外推，歌词和进度都跟手。":
      "Draggable. When casting, progress is smoothly extrapolated from the phone clock so lyrics and the slider stay in step.",
    "这首歌没有歌词？": "No lyrics for this song?",
    "这首歌没有歌词": "No lyrics for this song",
    "单曲循环": "Repeat one",
    "顺序播放": "In order",
    "列表循环": "Repeat all",
    "✕ 退出": "✕ Exit",
    "先播放一首歌": "Play a song first",
    "先选一首歌": "Pick a song first",
    "未知曲目": "Unknown track",
    "本地音乐": "Local music",
    "下载": "Download",
    "全部下载": "Download all",
    "全部加入列表": "Add all to queue",
    "没有可下载的曲目": "Nothing to download",
    "没有可加入的曲目": "Nothing to add",
    "边听边下载": "Download while playing",
    "边听边下载：": "Download while playing:",
    "边听边下载：开": "Download while playing: On",
    "边听边下载：关": "Download while playing: Off",
    "⤓ 边听边下载：关": "⤓ Download while playing: Off",
    "打开开关后，每播一首在线歌曲就自动加入下载队列，存到下载目录（默认 Music/音响管家，文件管理器可见）。本地歌曲不重复下载，同一首每次会话只下一次。":
      "With this on, every online song you play is queued for download automatically and saved to the download folder. Local songs are skipped, and each song is downloaded only once per session.",
    "下载状态": "Downloads",
    "⤓ 下载状态": "⤓ Downloads",
    "下载目录": "Download folder",
    "没有下载任务": "No download tasks",
    "默认保存在手机公共目录": "Saved to a public phone folder by default",
    "下载的歌会存到这里。默认放在公共音乐目录「Music/音响管家」，手机「文件管理」里能直接看到，系统音乐 App 也能扫到。":
      "Downloaded songs land here — by default in the public music folder “Music/音响管家”, visible in any file manager and picked up by the system music app.",
    "下载会按歌手存到当前音乐目录里；时长不足 1 分钟的试听片段会被自动跳过/删除。":
      "Downloads are filed by artist in the current music folder; previews shorter than one minute are skipped and deleted automatically.",
    "· 时长小于 1 分钟的试听片段会在下载预检时自动跳过。":
      "· Previews shorter than one minute are skipped during the download pre-check.",
    "· 每首歌右侧按钮：＋ 加入播放列表、⤓ 下载/查看。":
      "· Buttons on each row: ＋ adds to the queue, ⤓ downloads / views.",
    "· 自动扫描手机存储里的音频（MediaStore，无需手动刷新）。":
      "· Automatically scans audio on your phone (MediaStore — no manual refresh needed).",
    "📥 下载的文件在哪": "📥 Where are my downloads?",

    /* —— 音乐目录 / SMB —— */
    "添加本机目录": "Add local folder",
    "添加本地文件夹": "Add local folder",
    "添加网络共享": "Add network share",
    "加 SMB 共享": "Add SMB share",
    "添加 SMB 共享": "Add SMB share",
    "已添加的目录": "Added folders",
    "浏览…": "Browse…",
    "浏览共享": "Browse shares",
    "选择一个目录": "Pick a folder",
    "选这个目录": "Use this folder",
    "就用共享根目录": "Use share root",
    "已选共享根目录": "Share root selected",
    "已选子目录：": "Subfolder selected: ",
    "上一级": "Up",
    "主机 / IP，如 192.168.1.100": "Host / IP, e.g. 192.168.1.100",
    "共享名，如 music": "Share name, e.g. music",
    "用户名（访问受限时填）": "Username (if the share requires it)",
    "名称（如 NAS 音乐）": "Name (e.g. NAS Music)",
    "匿名免密：": "Anonymous: ",
    "匿名免密：开": "Anonymous: On",
    "匿名免密：关": "Anonymous: Off",
    "子目录（可选，点上面的「浏览共享」直接选）":
      "Subfolder (optional — use Browse shares above to pick one)",
    "测试连接": "Test connection",
    "挂载": "Mount",
    "SMB 连不上？": "SMB won't connect?",
    "检查用户名/密码、共享名大小写，以及 NAS 是否允许来宾访问。":
      "Check the username/password, the exact case of the share name, and whether the NAS allows guest access.",
    "共享需要允许写入，否则下载的歌存不进去。":
      "The share must be writable, otherwise downloads cannot be saved.",
    "服务器没列出共享，请手动填共享名": "The server didn't list shares — enter the share name manually",
    "没有发现共享服务器": "No share server found",
    "请填主机和共享名": "Enter the host and share name",
    "请先浏览选择一个目录": "Browse and pick a folder first",
    "这一层没有子目录": "No subfolders at this level",
    "（没有子目录，可直接选当前目录）": "(no subfolders — you can use this folder directly)",
    "「扫描局域网」自动找开 445 端口的 NAS/路由器；「浏览共享」逐层点进共享文件夹，选中的目录会加入本地曲库，不用手记路径。":
      "“Scan LAN” finds NAS drives and routers with port 445 open; “Browse shares” lets you walk into the folders layer by layer — the folder you pick joins your library, no path typing needed.",
    "不知道共享叫什么？先点「扫描局域网」把 NAS / 电脑找出来，再点「浏览共享」一层层点进去选目录，不用记名字。":
      "Don't know the share name? Tap “Scan LAN” to find your NAS or PC, then “Browse shares” and click your way to the folder — no names to memorise.",
    "「添加本机目录」会打开系统文件选择器，除了本地文件夹，还能选 SD 卡、U 盘，以及系统「文件」里已挂载好的网络位置。":
      "“Add local folder” opens the system file picker, where you can also choose SD cards, USB drives and any network location already mounted in Files.",
    "「曲库管理」里可添加多个音乐目录：设备存储文件夹、SMB 网络共享都可以。":
      "· Library Manager can hold several music folders — device storage folders and SMB shares alike.",
    "· 下载目录可在「曲库管理 → 下载目录」里用系统文件夹选择器任改（含 SD 卡/U 盘）。":
      "· The download folder can be changed in Library Manager → Download folder with the system picker (SD card / USB drive included).",
    "还没添加其它目录。手机里的歌靠系统媒体库自动收录。":
      "No extra folders yet. Music on your phone is picked up from the system media library automatically.",
    "SMB 面板：": "SMB panel:",
    "文件夹": "Folder",

    /* —— 设置 / 关于 / 使用说明 —— */
    "设置": "Settings",
    "更多设置": "More settings",
    "关于": "About",
    "关于本应用": "About",
    "使用说明": "User Guide",
    "📖 使用说明（详细教程）": "📖 User Guide (in depth)",
    "运行日志": "Runtime logs",
    "查看日志": "View logs",
    "清空记录": "Clear logs",
    "复制全部": "Copy all",
    "复制失败，请长按选择文本": "Copy failed — long-press to select the text",
    "暂无日志": "No logs yet",
    "暂无异常记录。": "No crashes logged.",
    "（暂无异常记录）": "(no crashes logged)",
    "后台异常会被自动拦截，不再让应用闪退；记录留在这里，可直接复制出来定位。":
      "Background crashes are caught automatically so the app never force-closes; they are logged here and can be copied out for troubleshooting.",
    "把复制出来的内容发出来，就能定位到底是哪一步出的问题。":
      "Paste the copied log into a bug report and we can pinpoint which step failed.",
    "本 App 只在你使用时工作；下拉通知栏的常驻通知用于保持后台播放不被系统杀掉。":
      "The app only runs while you use it; the persistent notification keeps background playback from being killed by the system.",
    "耗电与后台？": "Battery & background?",
    "读取权限：": "Read permission:",
    "已授权": "Granted",
    "不可读": "Not readable",
    "语言": "Language",
    "语言 / Language": "Language",
    "中文": "中文",
    "English": "English",
    "界面语言": "Interface language",
    "SyncDlnaPlay 是一款": "SyncDlnaPlay is a",
    "的音乐播放与 DLNA 投放工具：手机本机放歌、把歌投到局域网里的 DLNA 音响、扫描本地与 SMB 网络曲库、在线搜索并下载歌曲。不需要家里架设任何服务器，换 Wi-Fi、用流量热点都能用。":
      "music player and DLNA casting tool: play on your phone, cast to DLNA speakers on your LAN, scan local and SMB libraries, and search or download songs online. No home server needed — it works on any Wi-Fi or mobile hotspot.",
    "DLNA 控制、曲库、在线音源全部在手机本机运行，无需家中服务器。":
      "DLNA control, library and online sources all run on your phone — no home server required.",
    "SyncDlnaPlay · 独立运行版": "SyncDlnaPlay · Standalone",
    "局域网扫描是 v1.0「连外部服务」客户端模式的东西，独立版已不需要。":
      "LAN scanning belonged to the v1.0 “connect to external service” client mode; the standalone build doesn't need it.",
    "播控服务在本 App 进程内，所以这里不是": "The playback service lives inside this app's process, so this is not",

    /* —— 使用说明（教程正文） —— */
    "🚀 快速上手（3 步）": "🚀 Quick start (3 steps)",
    "① 连音响：": "① Connect a speaker: ",
    "② 选歌：": "② Pick songs: ",
    "③ 开播：": "③ Start playing: ",
    "底部「我的设备」→ 点「扫描」，发现的音响会列出，点一下选中（可多选多台同时响）。":
      "Go to My Devices → Scan. Any speakers found are listed; tap one to select it (select several to play on all of them).",
    "在「播放列表」点歌即播。声音从哪出由「正在播放」页的「输出方式」决定：音响 or 手机。":
      "Tap a song in the queue to play it. Output on the Now Playing page decides whether sound goes to the speaker or the phone.",
    "小提示：如果局域网里没发现任何音响，播放会自动回落到手机本机，不会卡在\"播放不了\"。":
      "Tip: if no speaker is found on your LAN, playback automatically falls back to this phone instead of failing.",
    "❓ 常见问题": "❓ FAQ",
    "一、连接页": "1. Connection",
    "二、启动与轮询": "2. Startup & polling",
    "三、Tab 切换": "3. Tab switching",
    "四、设备": "4. Devices",
    "五、曲库": "5. Library",
    "六、音乐目录管理（本地文件夹 / SMB 共享）": "6. Music folders (local folders / SMB shares)",
    "为什么不用 emoji：🖧 这类冷门 emoji 在不同 ROM 上有的渲染成方块、有的是彩色贴图，跟赛博朋克配色打架。统一用 currentColor 描边 SVG，颜色跟着文字走，任何设备上长得都一样。":
      "Why no emoji: obscure ones render as boxes on some ROMs and as colourful stickers on others, clashing with the cyberpunk palette. All icons are currentColor SVG strokes, so they inherit text colour and look identical everywhere.",
    "单击歌词行 = 跳转（延迟 300ms 执行，给双击留判断窗口）；350ms 内第二次点击 = 双击 → 进沉浸，并取消第一次排队的跳转。":
      "Single tap on a lyric line = seek (executed after a 300 ms delay to leave room for a double tap); a second tap within 350 ms = double tap → immersive mode, cancelling the queued seek.",
    "这些时间点共用这一句": "These timestamps share one line",
    "每个时间标签「到下一个标签之前」的文字就是它对应的歌词": "The text from each timestamp up to the next one is that line's lyric",
    "行内写法：[t1]第一句[t2]第二句 -> 各归各的": "Inline form: [t1]first line[t2]second line → each maps to its own time",
    "两种主流时间标签：[mm:ss.xx]（标准）与 [ss.xx]（纯秒，如元力KW）":
      "Two common timestamp formats: [mm:ss.xx] (standard) and [ss.xx] (seconds only, e.g. 元力KW)",
    "时间标签 [mm:ss.xx] -> 秒": "Timestamp [mm:ss.xx] → seconds",
    "取歌词：在线曲目问插件，本地曲目读同目录 .lrc": "Lyrics: fetched from the plugin for online tracks, or read from a sibling .lrc file for local ones",
    "没歌词 → 封面回归": "No lyrics → cover returns",
    "有歌词 → 歌词替代封面（同台合并）": "Lyrics available → they replace the cover (same stage)",
    "后端是异步起的，给它一点时间。失败也不再让用户填地址，只把原因说清楚。":
      "The backend starts asynchronously — give it a moment. On failure the user is no longer asked for an address, only told the reason.",
    "轻量触感反馈（部分 WebView 支持，不支持则静默）": "Light haptic feedback (silently skipped where the WebView doesn't support it)",
    "★默认」": "★ Default",
    "确认": "Confirm",

    /* —— 错误 / 提示前缀 —— */
    "网络错误": "Network error",
    "请求失败": "Request failed",
    "服务返回异常（不是 JSON）": "Bad service response (not JSON)",
    "内置服务地址无效，请重新启动 App。": "Invalid in-app service address. Please restart the app.",
    "内置服务没有启动成功。请重新启动 App；若反复失败，可在「设置 → 曲库管理 → 运行日志」查看原因。":
      "The in-app service failed to start. Please restart the app; if it keeps failing, check Settings → Library Manager → Runtime logs.",
    "读取文件失败": "Failed to read file",
    "当前目录没有曲目": "No tracks in this folder",
    "没有可用的播放地址": "No playable URL available",

    /* —— 补遗：覆盖率校验后补齐 —— */
    "已停止": "Stopped",
    "播放中": "Playing",
    "已暂停": "Paused",
    "缓冲中": "Buffering",
    "未播放": "Not playing",
    "返回列表": "Back to list",
    "同步校准": "Sync calibration",
    "打开看看": "Open it",
    "重新加载": "Reload",
    "选择": "Select",
    "扫描中…": "Scanning…",
    "已加入播放列表": "Added to queue",
    "✓ 已加入同步": "✓ Added to sync group",
    "↻ 重新扫描本机音乐": "↻ Rescan phone music",
    "📂 更改目录": "📂 Change folder",
    "、或": ", or",
    "首": "tracks",
    "· 已选": "· Selected",
    "· 内置多个 MusicFree 社区音源（元力系列等），支持关键词搜索与翻页。":
      "· Several community MusicFree sources are bundled — keyword search and paging supported.",
    "· 「曲库管理」里可添加多个音乐目录：设备存储文件夹、SMB 网络共享都可以。":
      "· Library Manager can hold several music folders — device storage folders and SMB shares alike.",
    "「添加本机目录」会打开系统文件选择器，除了本地文件夹，还能选 SD 卡、U 盘，以及系统「文件」里已挂载好的网络位置。":
      "“Add local folder” opens the system file picker, where you can also choose SD cards, USB drives and any network location already mounted in Files.",
    "以及系统「文件」里已挂载好的网络位置。": "and any network location already mounted in Files.",
    "「🔊 音响播放」把声音投到选中的 DLNA 音响；「📱 手机本机」用手机扬声器/耳机放。切换时另一边会自动停。":
      "“🔊 Speaker” casts to the selected DLNA speakers; “📱 This phone” plays through the phone's speaker or headphones. Switching stops the other side automatically.",
    "不知道共享叫什么？先点「扫描局域网」把 NAS / 电脑找出来， 再点「浏览共享」一层层点进去选目录，不用记名字。":
      "Don't know the share name? Tap “Scan LAN” to find your NAS or PC, then “Browse shares” and click your way to the folder — no names to memorise.",
    "两台以上音响同时播放时，声音会有一前一后。给先出声那台加一点延迟就能对齐； 点「设备」页的「同步校准」可以自动测。":
      "With two or more speakers the sound may drift apart. Add a little delay to the one that starts early to line them up; tap Sync calibration on the Devices page to measure automatically.",
    "安装后会立刻出现在在线音乐的「音源」下拉里。":
      "Once installed it shows up immediately in the Sources dropdown under Online Search.",
    "支持 MusicFree 插件的各种分发形式：插件源码网址、订阅链接、 分享码（一大串字符）、手机里的 .js / .json 文件。":
      "Every common MusicFree distribution format is supported: plugin source URL, subscription link, share code (a long string), or a local .js / .json file.",
    "，按「歌手/歌手 - 歌名」命名，任何文件管理器都能看到。下载状态可在「设置 → 下载状态」查看进度与失败原因。":
      ", filed as “Artist / Artist - Title” and visible in any file manager. Progress and errors are shown in Settings → Downloads.",
    "未发现音响": "No speakers found",
    "正在扫描…请稍候": "Scanning… please wait",
    /* 源码里跨行拼接成同一文本节点的长句（整句匹配） */
    "MusicFree 插件是社区维护的 .js 文件，常见于插件订阅链接或别人分享的分享码。 安装后会立刻出现在在线音乐的「音源」下拉里。":
      "MusicFree plugins are community-maintained .js files, usually shared as subscription links or share codes. Once installed, it appears immediately in the Sources dropdown under Online Search.",
    "「添加本机目录」会打开系统文件选择器，除了本地文件夹，还能选 SD 卡、U 盘， 以及系统「文件」里已挂载好的网络位置。":
      "“Add local folder” opens the system file picker — besides local folders you can pick SD cards, USB drives, and any network location already mounted in Files."
  };

  /* 词典键归一化：源码里的换行 / 多空格不影响命中 */
  (function () {
    var n = {};
    for (var k in EN) {
      if (Object.prototype.hasOwnProperty.call(EN, k)) n[norm(k)] = EN[k];
    }
    EN = n;
  })();

  /* ---------- 动态文案规则（顺序敏感，先长后短） ---------- */
  var STATE_EN = {
    "播放中": "Playing", "已暂停": "Paused", "已停止": "Stopped",
    "缓冲中": "Buffering", "离线": "Offline", "未播放": "Not playing", "未知": "Unknown"
  };
  var STATE_ALT = Object.keys(STATE_EN).join("|");

  var RX = [
    [/^(.+) · (播放中|已暂停|已停止|缓冲中|离线|未播放|未知)$/, function (m) { return m[1] + " · " + STATE_EN[m[2]]; }],
    [/^(\d+) 台设备$/, "$1 devices"],
    [/^(\d+) 台同步$/, "$1 synced"],
    [/^(\d+) 首 · 第 (\d+) 首$/, "$1 tracks · #$2"],
    [/^(\d+) 首$/, "$1 tracks"],
    [/^第 (\d+) 页 · (\d+) 首$/, "Page $1 · $2 tracks"],
    [/^第 (\d+) 页 · ([\d.]+) 首$/, "Page $1 · $2 tracks"],
    [/^已安装的音源（(\d+)）$/, "Installed sources ($1)"],
    [/^随 App 内置 · (.+)$/, "Bundled with app · $1"],
    [/^音量 · (.+)$/, "Volume · $1"],
    [/^上次扫描：(.*)$/, "Last scan: $1"],
    [/^扫描：(.*)$/, "Scan: $1"],
    [/^曲目数：(.*)$/, "Tracks: $1"],
    [/^读取权限：(.*)$/, "Read permission: $1"],
    [/^输出方式：(.*)$/, "Output: $1"],
    [/^提前 ([\d.]+)s$/, "+$1s"],
    [/^延后 ([\d.]+)s$/, "−$1s"],
    [/^歌词提前 ([\d.]+)s$/, "Lyrics +$1s"],
    [/^歌词延后 ([\d.]+)s$/, "Lyrics −$1s"],
    [/^已加入播放列表（(\d+) 首）$/, "Added $1 tracks to queue"],
    [/^已开始播放（(\d+) 首）$/, "Playing $1 tracks"],
    [/^开始下载 (\d+) 首$/, "Downloading $1 tracks"],
    [/^共 (\d+) 首$/, "$1 tracks"],
    [/^已选 (\d+) 个$/, "$1 selected"],
    [/^没找到「(.*)」$/, "Nothing found for “$1”"],
    [/^(\d+) 个子目录$/, "$1 subfolders"],
    [/^(\d+) 台设备（点一下填入主机）：$/, "$1 devices (tap to fill in the host):"],
    [/^正在扫描局域网，约 ([\d～~\-]+) 秒…$/, "Scanning LAN, about $1 s…"],
    /* 错误前缀（带冒号，后接原因） */
    [/^下载失败：(.*)$/, "Download failed: $1"],
    [/^播放失败：(.*)$/, "Playback failed: $1"],
    [/^本机播放失败：(.*)$/, "Phone playback failed: $1"],
    [/^设置失败：(.*)$/, "Failed to save: $1"],
    [/^选择失败：(.*)$/, "Selection failed: $1"],
    [/^切换失败：(.*)$/, "Switch failed: $1"],
    [/^加入失败：(.*)$/, "Failed to add: $1"],
    [/^移除失败：(.*)$/, "Remove failed: $1"],
    [/^安装失败：(.*)$/, "Install failed: $1"],
    [/^启动异常：(.*)$/, "Startup error: $1"],
    [/^解析失败：(.*)$/, "Resolve failed: $1"],
    [/^解析播放地址失败：(.*)$/, "Could not resolve the play URL: $1"],
    [/^跳转失败：(.*)$/, "Seek failed: $1"],
    [/^操作失败：(.*)$/, "Operation failed: $1"],
    [/^读取失败：(.*)$/, "Read failed: $1"],
    [/^搜索失败：(.*)$/, "Search failed: $1"],
    [/^音量设置失败：(.*)$/, "Volume change failed: $1"],
    [/^连接成功：(.*)$/, "Connected: $1"],
    [/^失败：(.*)$/, "Failed: $1"]
  ];

  /* ---------- 引擎 ---------- */
  function norm(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }

  function tr(text) {
    var k = norm(text);
    if (!k) return null;
    if (Object.prototype.hasOwnProperty.call(EN, k)) return EN[k];
    for (var i = 0; i < RX.length; i++) {
      if (RX[i][0].test(k)) {
        return typeof RX[i][1] === "function" ? k.replace(RX[i][0], RX[i][1]) : k.replace(RX[i][0], RX[i][1]);
      }
    }
    return null;
  }

  var ATTRS = ["placeholder", "title", "aria-label", "alt", "label"];

  function walk(root) {
    if (!root) return;
    var node, it = d.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    while ((node = it.nextNode())) {
      var raw = node.nodeValue;
      if (!raw) continue;
      var v = tr(raw);
      if (v != null && v !== norm(raw)) node.nodeValue = v;
    }
    if (root.querySelectorAll) {
      var els = root.querySelectorAll("[placeholder],[title],[aria-label],[alt]");
      for (var i = 0; i < els.length; i++) {
        for (var j = 0; j < ATTRS.length; j++) {
          var a = ATTRS[j], val = els[i].getAttribute(a);
          if (!val) continue;
          var t = tr(val);
          if (t != null) els[i].setAttribute(a, t);
        }
      }
    }
  }

  function detect() {
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { }
    if (saved === "en" || saved === "zh") return saved;
    var l = "";
    try { l = (navigator.languages && navigator.languages[0]) || navigator.language || ""; } catch (e) { }
    return /^zh/i.test(l) ? "zh" : "en";
  }

  function setLang(l) {
    try { localStorage.setItem(KEY, l); } catch (e) { }
    location.reload();
  }

  var w2 = w;
  w2.I18N = {
    get lang() { return cur; },
    t: tr,
    set: setLang,
    toggle: function () { setLang(cur === "en" ? "zh" : "en"); },
    apply: function () { if (cur === "en") walk(d.body); }
  };

  cur = detect();
  try { d.documentElement.setAttribute("lang", cur === "en" ? "en" : "zh-CN"); } catch (e) { }

  function boot() {
    if (cur !== "en") return;
    walk(d.body);
    var pending = null;
    var mo = new MutationObserver(function () {
      if (pending) return;
      // 24ms：短到肉眼不可见，又能把同一批重绘合并成一次遍历
      pending = setTimeout(function () { pending = null; walk(d.body); }, 24);
    });
    try { mo.observe(d.body, { childList: true, subtree: true, characterData: true }); } catch (e) { }
  }

  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", boot);
  else boot();
})(window, document);
