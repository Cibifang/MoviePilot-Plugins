
# MoviePilot library
from app.log import logger
from app.plugins import _PluginBase
from app.core.event import eventmanager
from app.schemas.types import EventType
from app.utils.system import SystemUtils

from typing import Any, List, Dict, Tuple
import subprocess
import os
import shutil
import time
import threading
try:
    from pyparsebluray import mpls
except:
    subprocess.run(["pip3", "install", "pyparsebluray"])
    subprocess.run(["pip3", "install", "ffmpeg-python"])
    
try:
    import ffmpeg
except:
    logger.error("requirements 安装失败")

class BDRemuxer3(_PluginBase):
    # 插件名称
    plugin_name = "BDMV Remuxer Test3"
    # 插件描述
    plugin_desc = "自动提取BDMV文件夹中的视频流和音频流，合并为MKV文件"
    # 插件图标
    plugin_icon = ""
    # 主题色
    plugin_color = "#3B5E8E"
    # 插件版本
    plugin_version = "1.1.1"
    # 插件作者
    plugin_author = "hankun"
    # 作者主页
    author_url = "https://github.com/hankunyu"
    # 插件配置项ID前缀
    plugin_config_prefix = "bdremuxer_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _delete = False
    _run_once = False
    _path = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._delete = config.get("delete")
            self._run_once = config.get("run_once")
            self._path = config.get("path")

        if self._enabled:
            logger.info("BD Remuxer 插件初始化完成")
            if self._run_once:
                # 查找所有BDMV目录
                bdmv_paths = self.find_all_bdmv_paths(os.path.dirname(self._path))

                if not bdmv_paths:
                    logger.info(f"在目标路径内未发现BDMV目录")
                    return

                logger.info(f"找到 {len(bdmv_paths)} 个BDMV目录")

                # 添加用户配置选项：处理策略
                process_strategy = self.get_config("bdmv_process_strategy") or "all"

                # 根据策略过滤BDMV目录
                if process_strategy == "first":
                    bdmv_paths = [bdmv_paths[0]]  # 只处理第一个
                elif process_strategy == "containing_name":
                    media_name = os.path.basename(target_file).split('.')[0]
                    bdmv_paths = [p for p in bdmv_paths if media_name in p]

                # 并行处理所有选定的BDMV目录
                threads = []
                MAX_THREADS = 3
                active_threads = 0
                for bdmv_path in bdmv_paths:
                    while active_threads >= MAX_THREADS:
                        time.sleep(5)  # 等待空闲线程
                    active_threads += 1
                    logger.info(f"开始处理BDMV: {bdmv_path}")
                    bd_root = os.path.dirname(bdmv_path)
                    thread = threading.Thread(target=self.process_wrapper, args=(bd_root, active_threads))
                    thread.start()
                    threads.append(thread)

                # 等待所有线程完成
                if self.get_config("wait_for_completion"):
                    for t in threads:
                        t.join()
                    logger.info("所有BDMV处理完成")

                self.update_config({
                    "enabled": self._enabled,
                    "delete": self._delete,
                    "run_once": False,
                    "path": self._path
                })

    def get_state(self) -> bool:
        return self._enabled
    
        
        
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass
    
    # 插件配置页面
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'delete',
                                            'label': '删除原始文件',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'path',
                                            'label': '手动指定BDMV文件夹路径',
                                            'rows': 1,
                                            'placeholder': '路径指向BDMV父文件夹',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'content': [
                                     {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'run_once',
                                            'label': '提取指定目录BDMV',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'flat',
                                            'text': '自用插件，可能不稳定',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "delete": False,
            "path": "",
            "run_once": False,
        }

    def get_page(self) -> List[dict]:
        pass
    
    def extract(self,bd_path : str):
        logger.info('开始提取BDMV。')
        output_name = os.path.basename(bd_path) + ".mkv"
        output_name = os.path.join(bd_path, output_name)
        bd_path = bd_path + '/BDMV'
        if not os.path.exists(bd_path):
            logger.info('失败。输入路径不存在BDMV文件夹')
            return
        mpls_path = bd_path + '/PLAYLIST/'
        if not os.path.exists(mpls_path):
            logger.info('失败。找不到PLAYLIST文件夹')
            return
        file_paths = self.get_all_m2ts(mpls_path)
        if not file_paths:
            logger.info('失败。找不到m2ts文件')
            return
        
        filelist_string = '\n'.join([f"file '{file}'" for file in file_paths])
        # 将filelist_string写入filelist.txt
        logger.info('搜索到需要提取的m2ts文件: ' + filelist_string)
        with open('/tmp/filelist.txt', 'w') as file:
            file.write(filelist_string)
            
        # 提取流程
        # 分析m2ts文件，提取视频流和音频流信息
        test_file = file_paths[0]
        probe = ffmpeg.probe(test_file)
        video_streams = [stream for stream in probe['streams'] if stream['codec_type'] == 'video']
        audio_streams = [stream for stream in probe['streams'] if stream['codec_type'] == 'audio']
        subtitle_streams = [stream for stream in probe['streams'] if stream['codec_type'] == 'subtitle']
        
        # 选取第一个视频流作为流编码信息
        video_codec = video_streams[0]['codec_name']
        # 获得每一条音频流的编码信息
        audio_codec = []
        for audio_stream in audio_streams:
            if audio_stream['codec_name'] == 'pcm_bluray':
                audio_codec.append('pcm_s16le')
            else:   
                audio_codec.append('copy')
            # print(audio_stream['codec_name'])
        
        # 获得每一条字幕流的编码信息
        subtitle_codec = []
        for subtitle_stream in subtitle_streams:
            if subtitle_stream['codec_name'] == 'hdmv_pgs_subtitle':
                subtitle_codec.append('copy')
            else:
                subtitle_codec.append('copy')
        
        # 整理参数作为字典
        dict = {  }
        for i in range(len(audio_codec)):
            dict[f'acodec:{i}'] = audio_codec[i]
        for i in range(len(subtitle_codec)):
            dict[f'scodec:{i}'] = subtitle_codec[i]
        # 使用ffmpeg合并m2ts文件
        try:
            (
            ffmpeg
            .input(
                '/tmp/filelist.txt', 
                format='concat', 
                safe=0, 
                )
            .output(
                output_name,
                vcodec='copy',
                **dict,
                map='0',  # 映射所有输入流
                map_metadata='0',  # 复制输入流的元数据
                map_chapters='0',  # 复制输入流的章节信息
            )
            .run()
            )
        except ffmpeg.Error as e:
            logger.error(e.stderr)
            logger.info('失败。')
            return
        # 删除原始文件
        if self._delete:
            shutil.rmtree(bd_path)
            logger.info('成功提取BDMV。并删除原始文件。')
        else:
            logger.info('成功提取BDMV。')
    

    def get_all_m2ts(self,mpls_path) -> list:
        """
        Get all useful m2ts file paths from mpls file
        :param mpls_path: path to mpls 00000 file
        :return: list of m2ts file paths
        """
        files = []
        play_items = []
        for file in os.listdir(mpls_path):
            if os.path.isfile(os.path.join(mpls_path, file)) and file.endswith('.mpls'):
                if file == '00000.mpls': continue # 跳过00000.mpls
                files.append(os.path.join(mpls_path, file))
        files.sort()
        for file in files:
            with open(file, 'rb') as mpls_file:
                header = mpls.load_movie_playlist(mpls_file)
                mpls_file.seek(header.playlist_start_address, os.SEEK_SET)
                pls = mpls.load_playlist(mpls_file)
                for item in pls.play_items:
                    if item.uo_mask_table == 0:
                        stream_path = os.path.dirname(os.path.dirname(file)) + '/STREAM/'
                        file_path = stream_path + item.clip_information_filename + '.m2ts'
                        play_items.append(file_path)
                if play_items:
                    return play_items
        return play_items


    def find_all_bdmv_paths(self, start_path: str, max_depth: int = 3) -> list:
        """
        查找所有符合条件的BDMV目录
        """
        bdmv_paths = []
        visited = set()

        def search(path, depth):
            if path in visited:
                return
            visited.add(path)

            # 跳过隐藏目录
            if any(part.startswith('.') for part in path.split(os.sep)):
                return

            # 检查当前路径是否有BDMV
            bdmv_candidate = os.path.join(path, "BDMV")
            if os.path.exists(bdmv_candidate):
                bdmv_paths.append(bdmv_candidate)
                # 找到后不再向下搜索该分支
                return

            # 深度限制
            if depth >= max_depth:
                return

            # 继续搜索子目录
            try:
                for entry in os.listdir(path):
                    full_path = os.path.join(path, entry)
                    if os.path.isdir(full_path):
                        search(full_path, depth + 1)
            except Exception as e:
                logger.error(f"搜索错误: {str(e)}")

        # 开始深度优先搜索
        search(start_path, 0)
        return bdmv_paths

    def process_wrapper(self, path, thread_counter):
        try:
            self.extract(path)
        finally:
            # 减少线程计数
            with threading.Lock():
                thread_counter -= 1

    @eventmanager.register(EventType.TransferComplete)
    def remuxer(self, event):
        if not self._enabled:
            return
        def __to_dict(_event):
            """
            递归将对象转换为字典
            """
            if isinstance(_event, dict):
                for k, v in _event.items():
                    _event[k] = __to_dict(v)
                return _event
            elif isinstance(_event, list):
                for i in range(len(_event)):
                    _event[i] = __to_dict(_event[i])
                return _event
            elif isinstance(_event, tuple):
                return tuple(__to_dict(list(_event)))
            elif isinstance(_event, set):
                return set(__to_dict(list(_event)))
            elif hasattr(_event, 'to_dict'):
                return __to_dict(_event.to_dict())
            elif hasattr(_event, '__dict__'):
                return __to_dict(_event.__dict__)
            elif isinstance(_event, (int, float, str, bool, type(None))):
                return _event
            else:
                return str(_event)
            
        raw_data = __to_dict(event.event_data)
        target_file = raw_data.get("transferinfo").get("file_list_new")[0]
        target_path = os.path.dirname(target_file)

        # 查找所有BDMV目录
        bdmv_paths = self.find_all_bdmv_paths(os.path.dirname(target_file))

        if not bdmv_paths:
            logger.info(f"在目标路径内未发现BDMV目录")
            return

        logger.info(f"找到 {len(bdmv_paths)} 个BDMV目录")

        # 添加用户配置选项：处理策略
        process_strategy = self.get_config("bdmv_process_strategy") or "all"

        # 根据策略过滤BDMV目录
        if process_strategy == "first":
            bdmv_paths = [bdmv_paths[0]]  # 只处理第一个
        elif process_strategy == "containing_name":
            media_name = os.path.basename(target_file).split('.')[0]
            bdmv_paths = [p for p in bdmv_paths if media_name in p]

        # 并行处理所有选定的BDMV目录
        threads = []
        MAX_THREADS = 3
        active_threads = 0
        for bdmv_path in bdmv_paths:
            while active_threads >= MAX_THREADS:
                time.sleep(5)  # 等待空闲线程
            active_threads += 1
            logger.info(f"开始处理BDMV: {bdmv_path}")
            bd_root = os.path.dirname(bdmv_path)
            thread = threading.Thread(target=self.process_wrapper, args=(bd_root, active_threads))
            thread.start()
            threads.append(thread)

        # 等待所有线程完成
        if self.get_config("wait_for_completion"):
            for t in threads:
                t.join()
            logger.info("所有BDMV处理完成")


    def stop_service(self):
        """
        退出插件
        """
        pass
