# MoviePilot library
from app.log import logger
from app.plugins import _PluginBase
from app.core.event import eventmanager
from app.schemas.types import EventType
from app.utils.system import SystemUtils
from app.chain.media import MediaChain
from app.core.metainfo import MetaInfo
from app.core.config import settings
from app import schemas
from app.schemas.types import MediaType, EventType, SystemConfigKey
from datetime import datetime

from typing import Any, List, Dict, Tuple, Optional
import subprocess
import os
import threading
import json
from app.plugins.danmu import danmu_generator as generator
    

class Danmu(_PluginBase):
    # 插件名称
    plugin_name = "弹幕刮削"
    # 插件描述
    plugin_desc = "使用弹弹play平台生成弹幕的字幕文件，实现弹幕播放。"
    # 插件图标
    plugin_icon =  "https://raw.githubusercontent.com/HankunYu/MoviePilot-Plugins/main/icons/danmu.png"
    # 主题色
    plugin_color = "#3B5E8E"
    # 插件版本
    plugin_version = "1.4.0"
    # 插件作者
    plugin_author = "hankun"
    # 作者主页
    author_url = "https://github.com/hankunyu"
    # 插件配置项ID前缀
    plugin_config_prefix = "danmu_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _width = 1920
    _height = 1080
    # 搞字体太复杂 以后再说
    # _fontface = 'Arial'
    _fontsize = 50
    _alpha = 0.8
    _duration = 15
    _path = ''
    _max_threads = 10
    _onlyFromBili = False
    _useTmdbID = True
    _auto_scrape = True
    # 新增重试相关配置
    _min_danmu_count = 100  # 最小弹幕数量要求 - 硬编码
    _max_retry_times = 10  # 最大重试次数 - 硬编码
    _enable_retry_task = True  # 是否启用重试任务
    
    # 重试任务列表 - 存储格式: {file_path: {"retry_count": int, "last_attempt": datetime, "file_path": str}}
    _retry_tasks = {}
    
    media_chain = MediaChain()
    
    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._width = config.get("width", 1920)
            self._height = config.get("height", 1080)
            # self._fontface = config.get("fontface")
            self._fontsize = config.get("fontsize", 50)
            self._alpha = config.get("alpha", 0.8)
            self._duration = config.get("duration", 15)
            self._path = config.get("path", "")
            self._onlyFromBili = config.get("onlyFromBili", False)
            self._useTmdbID = config.get("useTmdbID", True)
            self._auto_scrape = config.get("auto_scrape", False)
            self._enable_retry_task = config.get("enable_retry_task", True)
            # 加载重试任务列表
            retry_tasks_str = config.get("retry_tasks", "{}")
            try:
                loaded_tasks = json.loads(retry_tasks_str)
                self._retry_tasks = {}
                # 将字符串日期转换为datetime对象，并添加缺失字段的默认值
                for file_path, task_info in loaded_tasks.items():
                    try:
                        self._retry_tasks[file_path] = {
                            "retry_count": task_info.get("retry_count", 1),
                            "last_attempt": datetime.fromisoformat(task_info.get("last_attempt", datetime.now().isoformat())),
                            "file_path": task_info.get("file_path", file_path),
                            "last_danmu_count": task_info.get("last_danmu_count", 0)
                        }
                    except (ValueError, TypeError) as e:
                        logger.warning(f"跳过无效的重试任务 {file_path}: {e}")
                        continue
                logger.info(f"加载了 {len(self._retry_tasks)} 个重试任务")
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"加载重试任务失败，使用空列表: {e}")
                self._retry_tasks = {}
        if self._enabled:
            logger.info("弹幕加载插件已启用")

    def get_state(self) -> bool:
        return self._enabled
    
    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._enable_retry_task:
            return [{
                "id": "DanmuRetryTask",
                "name": "弹幕重试任务",
                "trigger": "cron",
                "func": self.auto_process_retry_tasks,
                "kwargs": {
                    "minute": 0,
                    "hour": "*/3",  # 每3小时执行一次
                    "day": "*",
                    "month": "*",
                    "day_of_week": "*"
                }
            }]
        return []
        
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        logger.info("获取插件API")
        return [{
            "path": "/generate_danmu_with_path",
            "endpoint": self.generate_danmu_global,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "刮削弹幕",
            "description": "根据设定的路径刮削弹幕" 
        },{
            "path": "/update_path",
            "endpoint": self.update_path,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "更新路径",
            "description": "更新刮削路径"
        },
        {
            "path": "/config",
            "endpoint": self._get_config,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "获取配置",
            "description": "获取插件配置"
        },
        {
            "path": "/config",
            "endpoint": self._save_config,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "保存配置",
            "description": "保存插件配置"
        },
        {
            "path": "/status",
            "endpoint": self._get_status,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "获取状态",
            "description": "获取当前刮削状态"
        },
        {
            "path": "/scan_path",
            "endpoint": self.scan_path,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "扫描路径",
            "description": "扫描路径下的媒体文件和弹幕信息，支持current_dir参数进行点击式导航"
        },
        {
            "path": "/scan_subfolder",
            "endpoint": self.scan_subfolder,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "扫描子文件夹",
            "description": "扫描指定子文件夹的内容"
        },
        {
            "path": "/generate_danmu",
            "endpoint": self.generate_danmu_single,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "生成单个文件弹幕",
            "description": "为指定文件生成弹幕"
        },
        {
            "path": "/retry_tasks",
            "endpoint": self.get_retry_tasks,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "获取重试任务列表",
            "description": "获取当前待重试的弹幕文件列表"
        },
        {
            "path": "/process_retry_tasks",
            "endpoint": self.process_retry_tasks,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "处理重试任务",
            "description": "对重试任务列表中的文件进行弹幕刮削"
        },
        {
            "path": "/clear_retry_tasks",
            "endpoint": self.clear_retry_tasks,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "清空重试任务",
            "description": "清空所有重试任务"
        },
        {
            "path": "/remove_retry_task",
            "endpoint": self.remove_retry_task,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "移除重试任务",
            "description": "移除指定的重试任务，需要file_path参数"
        }
        ]
     
    # 插件配置页面
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return None, self._get_config()
    
    def _get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return {
            "enabled": self._enabled,
            "width": self._width,
            "height": self._height,
            "fontsize": self._fontsize,
            "alpha": self._alpha,
            "duration": self._duration,
            "path": self._path,
            "onlyFromBili": self._onlyFromBili,
            "useTmdbID": self._useTmdbID,
            "auto_scrape": self._auto_scrape,
            "enable_retry_task": self._enable_retry_task
        }
        
    def _save_config(self, config: dict):
        """保存配置"""
        try:
            self._enabled = config.get("enabled", False)
            self._width = config.get("width", 1920)
            self._height = config.get("height", 1080)
            self._fontsize = config.get("fontsize", 50)
            self._alpha = config.get("alpha", 0.8)
            self._duration = config.get("duration", 15)
            self._path = config.get("path", "")
            self._onlyFromBili = config.get("onlyFromBili", False)
            self._useTmdbID = config.get("useTmdbID", True)
            self._auto_scrape = config.get("auto_scrape", False)
            self._enable_retry_task = config.get("enable_retry_task", True)
            
            # 准备重试任务数据
            retry_tasks_for_save = {}
            for file_path, task_info in self._retry_tasks.items():
                retry_tasks_for_save[file_path] = {
                    "retry_count": task_info["retry_count"],
                    "last_attempt": task_info["last_attempt"].isoformat(),
                    "file_path": task_info["file_path"],
                    "last_danmu_count": task_info.get("last_danmu_count", 0)
                }
            
            # 保存到系统配置
            self.update_config({
                "enabled": self._enabled,
                "width": self._width,
                "height": self._height,
                "fontsize": self._fontsize,
                "alpha": self._alpha,
                "duration": self._duration,
                "path": self._path,
                "onlyFromBili": self._onlyFromBili,
                "useTmdbID": self._useTmdbID,
                "auto_scrape": self._auto_scrape,
                "enable_retry_task": self._enable_retry_task,
                "retry_tasks": json.dumps(retry_tasks_for_save)
            })
            
            return schemas.Response(success=True, message="配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return schemas.Response(success=False, message=f"保存配置失败: {str(e)}")
    
    def get_page(self) -> List[dict]:
        """Vue mode doesn't use Vuetify page definitions."""
        return None
    
    # --- V2 Vue Interface Method ---
    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """Declare Vue rendering mode and assets path."""
        return "vue", "dist/assets"
    
    def _get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "enabled": self._enabled
        }

    def generate_danmu(self, file_path: str) -> Optional[str]:
        """
        生成弹幕文件
        :param file_path: 视频文件路径
        :return: 生成的弹幕文件路径，如果失败则返回None或失败原因字符串
        """
        meta = MetaInfo(file_path)
        tmdb_id = None
        episode = None
        release_date = None
        use_short_cache_ttl = False
        if self._useTmdbID:
            media_info = self.media_chain.recognize_media(meta=meta)
            if media_info:
                tmdb_id = media_info.tmdb_id
                episode = meta.episode.split('E')[1] if meta.episode else None
                release_date = media_info.release_date
                if release_date:
                    try:
                        release_datetime = datetime.strptime(release_date, '%Y-%m-%d')
                        is_recent = (datetime.now() - release_datetime).days < 90
                        if is_recent:
                            logger.info(f"媒体 {tmdb_id} 是最近90天内发布的内容,使用短缓存")
                            use_short_cache_ttl = True
                    except ValueError:
                        logger.warning(f"无效的发布日期格式: {release_date},使用默认缓存时间")
    
        try:
            result = generator.danmu_generator(
                file_path,
                self._width,
                self._height,
                'Arial',
                self._fontsize,
                self._alpha,
                self._duration,
                self._onlyFromBili,
                self._useTmdbID,
                tmdb_id,
                episode,
                60 if use_short_cache_ttl else None
            )
            
            # 检查弹幕生成结果
            ass_file = f"{os.path.splitext(file_path)[0]}.danmu.ass"
            danmu_count = 0
            
            # 如果返回字符串且包含弹幕数量为0，说明是失败原因
            if isinstance(result, str) and result.startswith('弹幕数量为0'):
                logger.info(result)
                # 检查是否需要添加到重试任务
                self._add_to_retry_if_needed(file_path, 0)
                return result
            
            # 检查生成的弹幕文件
            if os.path.exists(ass_file):
                danmu_count = self.count_danmu_lines(ass_file)
                logger.info(f"弹幕生成完成，弹幕数量: {danmu_count}")
                
                # 检查弹幕数量是否满足要求
                if self._enable_retry_task and danmu_count < self._min_danmu_count:
                    logger.warning(f"弹幕数量 ({danmu_count}) 少于最小要求 ({self._min_danmu_count})，添加到重试任务")
                    self._add_to_retry_if_needed(file_path, danmu_count)
                else:
                    # 弹幕数量满足要求，如果之前在重试列表中则移除
                    if file_path in self._retry_tasks:
                        logger.info(f"弹幕数量满足要求，从重试任务中移除: {file_path}")
                        del self._retry_tasks[file_path]
                        self._save_retry_tasks()
            else:
                logger.warning(f"弹幕文件不存在: {ass_file}")
                # 没有生成弹幕文件，添加到重试任务
                self._add_to_retry_if_needed(file_path, 0)
                
            return result
        except Exception as e:
            logger.error(f"生成弹幕失败: {e}")
            # 生成失败，添加到重试任务
            self._add_to_retry_if_needed(file_path, 0)
            return f"生成弹幕失败: {str(e)}"

    def _add_to_retry_if_needed(self, file_path: str, danmu_count: int):
        """
        根据弹幕数量判断是否需要添加到重试任务
        :param file_path: 文件路径
        :param danmu_count: 弹幕数量
        """
        if not self._enable_retry_task:
            return
            
        # 检查文件是否已在重试列表中
        if file_path in self._retry_tasks:
            # 更新重试次数和最后尝试时间
            self._retry_tasks[file_path]["retry_count"] += 1
            self._retry_tasks[file_path]["last_attempt"] = datetime.now()
            
            # 检查是否达到最大重试次数
            if self._retry_tasks[file_path]["retry_count"] >= self._max_retry_times:
                logger.warning(f"文件 {file_path} 达到最大重试次数 ({self._max_retry_times})，从重试列表中移除")
                del self._retry_tasks[file_path]
            else:
                logger.info(f"更新重试任务: {file_path}，重试次数: {self._retry_tasks[file_path]['retry_count']}")
        else:
            # 添加新的重试任务
            if danmu_count < self._min_danmu_count:
                self._retry_tasks[file_path] = {
                    "retry_count": 1,
                    "last_attempt": datetime.now(),
                    "file_path": file_path,
                    "last_danmu_count": danmu_count
                }
                logger.info(f"添加新的重试任务: {file_path}，当前弹幕数量: {danmu_count}")
        
        # 保存重试任务到配置
        self._save_retry_tasks()

    def _save_retry_tasks(self):
        """
        保存重试任务列表到配置
        """
        try:
            # 将datetime对象转换为字符串以便JSON序列化
            retry_tasks_for_save = {}
            for file_path, task_info in self._retry_tasks.items():
                retry_tasks_for_save[file_path] = {
                    "retry_count": task_info["retry_count"],
                    "last_attempt": task_info["last_attempt"].isoformat(),
                    "file_path": task_info["file_path"],
                    "last_danmu_count": task_info.get("last_danmu_count", 0)
                }
            
            # 获取当前配置
            current_config = self._get_config()
            current_config["retry_tasks"] = json.dumps(retry_tasks_for_save)
            
            # 更新配置
            self.update_config(current_config)
            logger.debug("重试任务列表已保存到配置")
        except Exception as e:
            logger.error(f"保存重试任务失败: {e}")

    def update_path(self, path: str):
        """
        更新路径
        """
        self._path = path
        logger.info(f"更新路径: {self._path}")
        
    def generate_danmu_global(self):
        """
        全局刮削弹幕
        """
        if not self._path:
            logger.warning("未设置刮削路径，跳过刮削")
            return schemas.Response(success=False, message="没有设定路径")

        logger.info("开始弹幕刮削")
        
        threading_list = []
        paths = [path.strip() for path in self._path.split('\n') if path.strip()]

        # 计算总文件数
        total_files = 0
        for path in paths:
            if not os.path.exists(path):
                logger.warning(f"路径不存在: {path}")
                return schemas.Response(success=False, message=f"路径不存在: {path}")

            if os.path.isfile(path) and path.endswith(('.mp4', '.mkv')):
                total_files += 1
            else:
                for root, _, files in os.walk(path):
                    total_files += sum(1 for file in files if file.endswith(('.mp4', '.mkv')))

        for path in paths:
            if not os.path.exists(path):
                continue

            # 检查是否是单个文件
            if os.path.isfile(path) and path.endswith(('.mp4', '.mkv')):
                logger.info(f"刮削单个文件：{path}")
                if len(threading_list) >= self._max_threads:
                    threading_list[0].join()
                    threading_list.pop(0)

                thread = threading.Thread(
                    target=self.generate_danmu,
                    args=(path,)
                )
                thread.start()
                threading_list.append(thread)
                continue

            # 处理目录
            logger.info(f"刮削路径：{path}")
            for root, _, files in os.walk(path):
                for file in files:
                    if file.endswith(('.mp4', '.mkv')):
                        if len(threading_list) >= self._max_threads:
                            threading_list[0].join()
                            threading_list.pop(0)

                        target_file = os.path.join(root, file)
                        logger.info(f"开始生成弹幕文件：{target_file}")
                        thread = threading.Thread(
                            target=self.generate_danmu,
                            args=(target_file,)
                        )
                        thread.start()
                        threading_list.append(thread)

        for thread in threading_list:
            thread.join()

        logger.info("弹幕刮削完成")
        return schemas.Response(success=True, message="弹幕刮削完成")
    
    @eventmanager.register(EventType.TransferComplete)
    def generate_danmu_after_transfer(self, event):
        """
        传输完成后生成弹幕
        """
        if not self._enabled or not self._auto_scrape:
            return

        def __to_dict(_event):
            """
            递归将对象转换为字典
            """
            if isinstance(_event, dict):
                return {k: __to_dict(v) for k, v in _event.items()}
            elif isinstance(_event, list):
                return [__to_dict(item) for item in _event]
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

        try:
            raw_data = __to_dict(event.event_data)
            target_file = raw_data.get("transferinfo", {}).get("file_list_new", [None])[0]
            
            if not target_file:
                logger.warning("未找到目标文件")
                return

            logger.info(f"开始生成弹幕文件：{target_file}")
            thread = threading.Thread(
                target=self.generate_danmu,
                args=(target_file,)
            )
            thread.start()
        except Exception as e:
            logger.error(f"处理传输完成事件失败: {e}")

    def stop_service(self):
        """
        退出插件
        """
        pass

    def count_danmu_lines(self, ass_file: str) -> int:
        """
        计算弹幕文件中的弹幕数量
        :param ass_file: 弹幕文件路径
        :return: 弹幕数量
        """
        try:
            if not os.path.exists(ass_file):
                return 0
            count = 0
            with open(ass_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('Dialogue:'):
                        count += 1
            return count
        except Exception as e:
            logger.error(f"计算弹幕数量失败: {e}")
            return 0

    def scan_path(self, path: str = None, current_dir: str = None) -> Dict[str, Any]:
        """
        扫描路径下的媒体文件和弹幕信息
        :param path: 配置的根路径
        :param current_dir: 当前浏览的目录（用于点击式导航）
        :return: 目录结构信息
        """
        logger.debug(f"开始扫描路径: {path if path else self._path}, 当前目录: {current_dir}")
        
        # 如果有current_dir，直接扫描该目录
        if current_dir:
            return self.scan_subfolder(current_dir)
        
        # 否则使用配置的路径
        if not path:
            path = self._path
            
        if not path:
            logger.debug("未设置扫描路径，返回错误")
            return schemas.Response(success=False, message="路径不存在")
        
        # 处理多路径情况
        paths = [p.strip() for p in path.split('\n') if p.strip()]
        logger.debug(f"解析到 {len(paths)} 个有效路径")
        
        if len(paths) > 1:
            # 多路径情况，返回多个根目录
            logger.debug("处理多路径情况")
            result = {
                "name": "根目录",
                "path": "",
                "type": "root",
                "is_root": True,
                "children": []
            }
            
            for single_path in paths:
                logger.debug(f"处理子路径: {single_path}")
                if os.path.exists(single_path):
                    child_result = self._scan_current_directory(single_path)
                    result["children"].append(child_result)
                else:
                    logger.warning(f"路径不存在: {single_path}")
                    
            logger.debug(f"多路径扫描完成，共 {len(result['children'])} 个有效路径")
            return schemas.Response(success=True, data=result)
        elif len(paths) == 1:
            # 单路径情况
            single_path = paths[0]
            logger.debug(f"处理单路径: {single_path}")
            if not os.path.exists(single_path):
                logger.warning(f"路径不存在: {single_path}")
                return schemas.Response(success=False, message=f"路径不存在: {single_path}")
            
            result = self._scan_current_directory(single_path, is_root=True)
            logger.debug("单路径扫描完成")
            return schemas.Response(success=True, data=result)
        else:
            logger.debug("没有提供有效路径")
            return schemas.Response(success=False, message="未提供有效路径")

    def _scan_current_directory(self, path: str, is_root: bool = False) -> Dict[str, Any]:
        """
        扫描当前目录的直接内容（不递归）
        :param path: 要扫描的目录路径
        :param is_root: 是否为根目录
        :return: 目录结构信息
        """
        logger.debug(f"开始扫描当前目录: {path}, 是否为根目录: {is_root}")
        result = {
            "name": os.path.basename(path) or path,
            "path": path,
            "type": "directory",
            "is_root": is_root,
            "children": []
        }
        
        try:
            # 如果是文件，直接返回文件信息
            if os.path.isfile(path):
                logger.debug(f"{path} 是文件")
                if path.endswith(('.mp4', '.mkv')):
                    logger.debug(f"{path} 是媒体文件")
                    result["type"] = "media"
                    # 检查是否存在对应的弹幕文件
                    ass_file = f"{os.path.splitext(path)[0]}.danmu.ass"
                    logger.debug(f"检查弹幕文件: {ass_file}")
                    if os.path.exists(ass_file):
                        danmu_count = self.count_danmu_lines(ass_file)
                        result["danmu_count"] = danmu_count
                        logger.debug(f"找到弹幕文件，数量: {danmu_count}")
                    else:
                        result["danmu_count"] = 0
                        logger.debug("未找到弹幕文件")
                return result
                
            # 扫描目录的直接子项
            logger.debug(f"{path} 是目录，开始扫描直接子项")
            media_count = 0
            dir_count = 0
            
            try:
                items = os.listdir(path)
                logger.debug(f"{path} 目录中共有 {len(items)} 个项目")
            except PermissionError:
                logger.warning(f"无权限访问目录: {path}")
                result["error"] = "无权限访问该目录"
                return result
            except Exception as e:
                logger.warning(f"列出目录内容失败: {path}, 错误: {str(e)}")
                result["error"] = f"列出目录内容失败: {str(e)}"
                return result
            
            # 先处理目录，再处理文件
            directories = []
            files = []
            
            for item in items:
                # 跳过隐藏文件和系统文件
                if item.startswith('.'):
                    continue
                    
                item_path = os.path.join(path, item)
                
                if os.path.isdir(item_path):
                    directories.append((item, item_path))
                elif os.path.isfile(item_path) and item.endswith(('.mp4', '.mkv')):
                    files.append((item, item_path))
            
            # 添加目录到结果
            for item, item_path in sorted(directories):
                logger.debug(f"发现目录: {item_path}")
                dir_count += 1
                child = {
                    "name": item,
                    "path": item_path,
                    "type": "directory",
                    "children": []
                }
                result["children"].append(child)
            
            # 添加媒体文件到结果
            for item, item_path in sorted(files):
                logger.debug(f"发现媒体文件: {item_path}")
                media_count += 1
                child = {
                    "name": item,
                    "path": item_path,
                    "type": "media",
                    "children": []
                }
                # 检查是否存在对应的弹幕文件
                ass_file = f"{os.path.splitext(item_path)[0]}.danmu.ass"
                logger.debug(f"检查弹幕文件: {ass_file}")
                if os.path.exists(ass_file):
                    danmu_count = self.count_danmu_lines(ass_file)
                    child["danmu_count"] = danmu_count
                    logger.debug(f"找到弹幕文件，数量: {danmu_count}")
                else:
                    child["danmu_count"] = 0
                    logger.debug(f"未找到弹幕文件: {ass_file}")
                result["children"].append(child)
            
            logger.debug(f"目录 {path} 扫描完成，发现 {media_count} 个媒体文件，{dir_count} 个子目录")
            return result
        except Exception as e:
            logger.error(f"扫描路径失败: {path}, 错误: {e}")
            # 出错时返回基本信息，不中断整个扫描
            result["error"] = str(e)
            return result

    def generate_danmu_single(self, file_path: str) -> Dict[str, Any]:
        """
        为单个文件生成弹幕
        :param file_path: 媒体文件路径
        :return: 生成结果
        """
        if not file_path or not os.path.exists(file_path):
            return schemas.Response(success=False, message="文件不存在")
            
        if not file_path.endswith(('.mp4', '.mkv')):
            return schemas.Response(success=False, message="不支持的文件格式")
            
        try:
            result = self.generate_danmu(file_path)
            if result is None:
                return schemas.Response(success=False, message="弹幕生成失败")
            # 如果是字符串且不是弹幕文件路径，说明是失败原因
            if isinstance(result, str) and not result.endswith('.ass'):
                return schemas.Response(success=False, message=result)
            # 正常生成
            ass_file = f"{os.path.splitext(file_path)[0]}.danmu.ass"
            danmu_count = self.count_danmu_lines(ass_file)
            logger.info(f"生成弹幕成功，弹幕数量: {danmu_count}")
            if danmu_count == 0:
                return schemas.Response(success=False, message="弹幕数量为0 跳过生成")
            return schemas.Response(
                success=True,
                message="弹幕生成成功",
                data={
                    "danmu_count": danmu_count,
                    "file_path": file_path
                }
            )
        except Exception as e:
            logger.error(f"生成弹幕失败: {e}")
            return schemas.Response(success=False, message=f"生成弹幕失败: {str(e)}")

    def scan_subfolder(self, subfolder_path: str = None) -> Dict[str, Any]:
        """
        专门用于扫描子文件夹的内容（点击式导航）
        :param subfolder_path: 子文件夹路径
        :return: 该子文件夹的内容
        """
        logger.debug(f"扫描子文件夹: {subfolder_path}")
        
        if not subfolder_path:
            logger.warning("未提供子文件夹路径")
            return schemas.Response(success=False, message="未提供子文件夹路径")
        
        if not os.path.exists(subfolder_path):
            logger.warning(f"子文件夹不存在: {subfolder_path}")
            return schemas.Response(success=False, message="文件夹不存在")
        
        if not os.path.isdir(subfolder_path):
            logger.warning(f"指定路径不是文件夹: {subfolder_path}")
            return schemas.Response(success=False, message="指定路径不是文件夹")
        
        try:
            # 检查当前路径是否为用户配置的根路径之一
            is_root = False
            if self._path:
                root_paths = [p.strip() for p in self._path.split('\n') if p.strip()]
                is_root = subfolder_path in root_paths
            
            # 直接扫描这个子文件夹的内容
            result = self._scan_current_directory(subfolder_path, is_root=is_root)
            logger.debug("子文件夹扫描完成")
            return schemas.Response(success=True, data=result)
        except Exception as e:
            logger.error(f"扫描子文件夹失败: {subfolder_path}, 错误: {e}")
            return schemas.Response(success=False, message=f"扫描子文件夹失败: {str(e)}")

    def get_retry_tasks(self) -> Dict[str, Any]:
        """
        获取重试任务列表
        :return: 重试任务列表
        """
        # 转换datetime对象为字符串以便前端显示
        display_tasks = {}
        for file_path, task_info in self._retry_tasks.items():
            display_tasks[file_path] = {
                "retry_count": task_info["retry_count"],
                "last_attempt": task_info["last_attempt"].strftime("%Y-%m-%d %H:%M:%S"),
                "file_path": task_info["file_path"],
                "last_danmu_count": task_info.get("last_danmu_count", 0)
            }
        
        return schemas.Response(
            success=True,
            message=f"获取到 {len(display_tasks)} 个重试任务",
            data={
                "tasks": display_tasks,
                "total": len(display_tasks),
                "min_danmu_count": self._min_danmu_count,
                "max_retry_times": self._max_retry_times
            }
        )

    def process_retry_tasks(self) -> Dict[str, Any]:
        """
        处理重试任务
        :return: 处理结果
        """
        if not self._retry_tasks:
            return schemas.Response(success=True, message="没有待处理的重试任务")
        
        logger.info(f"开始处理 {len(self._retry_tasks)} 个重试任务")
        processed_count = 0
        success_count = 0
        failed_count = 0
        removed_count = 0
        
        # 创建副本以避免在迭代时修改字典
        tasks_to_process = list(self._retry_tasks.items())
        
        for file_path, task_info in tasks_to_process:
            # 检查文件是否仍然存在
            if not os.path.exists(file_path):
                logger.warning(f"重试任务文件不存在，移除: {file_path}")
                if file_path in self._retry_tasks:
                    del self._retry_tasks[file_path]
                removed_count += 1
                continue
            
            # 检查是否达到最大重试次数
            if task_info["retry_count"] >= self._max_retry_times:
                logger.warning(f"文件 {file_path} 已达到最大重试次数 ({self._max_retry_times})，移除")
                if file_path in self._retry_tasks:
                    del self._retry_tasks[file_path]
                removed_count += 1
                continue
            
            logger.info(f"处理重试任务: {file_path} (第 {task_info['retry_count'] + 1} 次尝试)")
            
            try:
                # 生成弹幕（这会自动更新重试任务状态）
                result = self.generate_danmu(file_path)
                processed_count += 1
                
                # 检查结果
                if result and not (isinstance(result, str) and result.startswith('弹幕数量为0')):
                    # 检查弹幕文件是否满足要求
                    ass_file = f"{os.path.splitext(file_path)[0]}.danmu.ass"
                    if os.path.exists(ass_file):
                        danmu_count = self.count_danmu_lines(ass_file)
                        if danmu_count >= self._min_danmu_count:
                            success_count += 1
                            logger.info(f"重试成功: {file_path}，弹幕数量: {danmu_count}")
                        else:
                            failed_count += 1
                            logger.info(f"重试失败: {file_path}，弹幕数量仍不足: {danmu_count}")
                    else:
                        failed_count += 1
                        logger.warning(f"重试失败: {file_path}，弹幕文件不存在")
                else:
                    failed_count += 1
                    logger.warning(f"重试失败: {file_path}，{result}")
                    
            except Exception as e:
                logger.error(f"处理重试任务失败: {file_path}，错误: {e}")
                failed_count += 1
        
        # 保存更新后的重试任务列表
        self._save_retry_tasks()
        
        result_message = f"重试任务处理完成。处理: {processed_count}, 成功: {success_count}, 失败: {failed_count}, 移除: {removed_count}, 剩余: {len(self._retry_tasks)}"
        logger.info(result_message)
        
        return schemas.Response(
            success=True,
            message=result_message,
            data={
                "processed": processed_count,
                "success": success_count,
                "failed": failed_count,
                "removed": removed_count,
                "remaining": len(self._retry_tasks)
            }
        )

    def clear_retry_tasks(self) -> Dict[str, Any]:
        """
        清空重试任务
        :return: 清空结果
        """
        task_count = len(self._retry_tasks)
        self._retry_tasks = {}
        self._save_retry_tasks()
        
        logger.info(f"已清空 {task_count} 个重试任务")
        return schemas.Response(
            success=True,
            message=f"已清空 {task_count} 个重试任务"
        )

    def remove_retry_task(self, file_path: str) -> Dict[str, Any]:
        """
        移除重试任务
        :param file_path: 要移除的重试任务的文件路径
        :return: 移除结果
        """
        if not file_path:
            return schemas.Response(success=False, message="文件路径不能为空")
            
        if file_path in self._retry_tasks:
            del self._retry_tasks[file_path]
            self._save_retry_tasks()
            logger.info(f"重试任务已移除: {file_path}")
            return schemas.Response(
                success=True,
                message=f"重试任务已移除: {file_path}"
            )
        else:
            return schemas.Response(
                success=False,
                message=f"未找到重试任务: {file_path}"
            )

    def auto_process_retry_tasks(self):
        """
        定时自动处理重试任务
        """
        try:
            if not self._enabled or not self._enable_retry_task:
                logger.debug("弹幕插件或重试任务功能未启用，跳过定时处理")
                return
                
            if not self._retry_tasks:
                logger.debug("没有待处理的重试任务")
                return
                
            logger.info(f"定时任务开始处理 {len(self._retry_tasks)} 个重试任务")
            
            # 调用现有的处理重试任务方法
            result = self.process_retry_tasks()
            
            if result.success:
                logger.info(f"定时任务完成，{result.message}")
            else:
                logger.warning(f"定时任务处理失败: {result.message}")
                
        except Exception as e:
            logger.error(f"定时处理重试任务失败: {e}")
