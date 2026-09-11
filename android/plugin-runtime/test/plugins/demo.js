/**
 * 示例插件（仅用于验证整条链路：搜索 -> 解析直链 -> 代理 -> 音响播放）。
 * 使用 SoundHelix 的公开样例音频，无需任何 Key / Header。
 * 接好你自己的 MusicFree 插件时，把它从 /plugins 里删掉即可。
 */
const SONGS = [
  { id: 's1', title: 'Demo 1 - SoundHelix', artist: 'SoundHelix', album: 'Demo', artwork: '', duration: 372, url: 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3' },
  { id: 's2', title: 'Demo 2 - SoundHelix', artist: 'SoundHelix', album: 'Demo', artwork: '', duration: 426, url: 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3' },
  { id: 's3', title: 'Demo 3 - SoundHelix', artist: 'SoundHelix', album: 'Demo', artwork: '', duration: 503, url: 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3' },
];

module.exports = {
  platform: 'Demo',
  version: '1.0.0',
  author: 'bridge',
  async search(query, page, type) {
    const q = (query || '').toLowerCase();
    const data = SONGS.filter(s => !q || s.title.toLowerCase().includes(q) || s.artist.toLowerCase().includes(q));
    return {
      isEnd: true,
      data: data.map(s => ({ id: s.id, title: s.title, artist: s.artist, album: s.album, artwork: s.artwork, duration: s.duration })),
    };
  },
  async getMediaSource(musicItem, quality) {
    const s = SONGS.find(x => x.id === (musicItem && musicItem.id)) || SONGS[0];
    return { url: s.url };
  },
};
