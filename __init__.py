import json
import os
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from collections import defaultdict

from nonebot import on_command, get_driver, require, get_bot
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.permission import SUPERUSER
from nonebot.rule import to_me
from nonebot.params import CommandArg
from nonebot.log import logger

# 数据存储路径
DATA_DIR = Path("data/nonebot_plugin_group_member_manager")
DATA_FILE = DATA_DIR / "data.json"

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


class DataManager:
    """数据管理类"""
    
    def __init__(self):
        self.data = self.load_data()
    
    def load_data(self) -> Dict:
        """加载数据"""
        if not DATA_FILE.exists():
            return {
                "bindings": {},  # 格式: {"当前群号": {"target_group": "目标群号", "inactive_months": 6}}
                "whitelist": defaultdict(set),  # 格式: {"群号": {qq号集合}}
            }
        
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 转换whitelist为set类型
                if "whitelist" in data:
                    data["whitelist"] = {k: set(v) for k, v in data["whitelist"].items()}
                else:
                    data["whitelist"] = defaultdict(set)
                return data
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return {
                "bindings": {},
                "whitelist": defaultdict(set),
            }
    
    def save_data(self):
        """保存数据"""
        try:
            # 转换set为list用于JSON序列化
            save_data = self.data.copy()
            save_data["whitelist"] = {k: list(v) for k, v in self.data["whitelist"].items()}
            
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
    
    def bind_group(self, current_group: str, target_group: str) -> bool:
        """绑定群聊"""
        self.data["bindings"][current_group] = {
            "target_group": target_group,
            "inactive_months": 6  # 默认6个月
        }
        self.save_data()
        return True
    
    def unbind_group(self, current_group: str) -> bool:
        """取消绑定"""
        if current_group in self.data["bindings"]:
            target_group = self.data["bindings"][current_group]["target_group"]
            del self.data["bindings"][current_group]
            # 删除对应的白名单
            if target_group in self.data["whitelist"]:
                del self.data["whitelist"][target_group]
            self.save_data()
            return True
        return False
    
    def set_inactive_months(self, current_group: str, months: int) -> bool:
        """设定不活跃月数"""
        if current_group in self.data["bindings"]:
            self.data["bindings"][current_group]["inactive_months"] = months
            self.save_data()
            return True
        return False
    
    def get_binding(self, current_group: str) -> Optional[Dict]:
        """获取绑定信息"""
        return self.data["bindings"].get(current_group)
    
    def add_whitelist(self, group_id: str, user_id: str):
        """添加白名单"""
        if group_id not in self.data["whitelist"]:
            self.data["whitelist"][group_id] = set()
        self.data["whitelist"][group_id].add(user_id)
        self.save_data()
    
    def get_whitelist(self, group_id: str) -> Set[str]:
        """获取白名单"""
        return self.data["whitelist"].get(group_id, set())


# 创建数据管理器实例
data_manager = DataManager()

# 命令处理器
bind_group = on_command("gmm绑定主群", permission=SUPERUSER, priority=5)
unbind_group = on_command("gmm取消绑定", permission=SUPERUSER, priority=5)
set_inactive = on_command("gmm设定不活跃月数", permission=SUPERUSER, priority=5)
check_inactive = on_command("gmm查看不活跃成员", priority=5)
add_whitelist = on_command("gmm设定白名单", priority=5)
remove_inactive = on_command("gmm删除不活跃成员", priority=5)
remove_whitelist = on_command("gmm删除白名单", permission=SUPERUSER, priority=5)

@bind_group.handle()
async def handle_bind_group(bot: Bot, event: GroupMessageEvent, args=CommandArg()):
    """绑定主群"""
    args_text = str(args).strip()
    if not args_text:
        await bind_group.send("请输入要绑定的群号")
        return
    
    try:
        target_group = args_text
        current_group = str(event.group_id)
        
        # 检查目标群是否存在
        try:
            group_info = await bot.get_group_info(group_id=int(target_group))
        except Exception:
            await bind_group.send(f"群号 {target_group} 不存在或机器人不在该群中")
            return
        
        if data_manager.bind_group(current_group, target_group):
            await bind_group.send(f"成功绑定群 {group_info['group_name']}({target_group})")
        else:
            await bind_group.send("绑定失败")
    except ValueError:
        await bind_group.send("请输入有效的群号")


@unbind_group.handle()
async def handle_unbind_group(bot: Bot, event: GroupMessageEvent):
    """取消绑定"""
    current_group = str(event.group_id)
    
    binding = data_manager.get_binding(current_group)
    if not binding:
        await unbind_group.send("当前群未绑定任何主群")
        return
    
    if data_manager.unbind_group(current_group):
        await unbind_group.send(f"已取消绑定群 {binding['target_group']}，白名单已清空")
    else:
        await unbind_group.send("取消绑定失败")


@set_inactive.handle()
async def handle_set_inactive(bot: Bot, event: GroupMessageEvent, args=CommandArg()):
    """设定不活跃月数"""
    args_text = str(args).strip()
    if not args_text:
        await set_inactive.send("请输入不活跃月数")
        return
    
    try:
        months = int(args_text)
        if months <= 0:
            await set_inactive.send("月数必须大于0")
            return
            
        current_group = str(event.group_id)
        
        if data_manager.set_inactive_months(current_group, months):
            await set_inactive.send(f"已设定不活跃判定月数为 {months} 个月")
        else:
            await set_inactive.send("当前群未绑定主群，请先绑定主群")
    except ValueError:
        await set_inactive.send("请输入有效的数字")


@check_inactive.handle()
async def handle_check_inactive(bot: Bot, event: GroupMessageEvent):
    """查看不活跃成员"""
    current_group = str(event.group_id)
    binding = data_manager.get_binding(current_group)
    
    if not binding:
        await check_inactive.send("当前群未绑定主群，请先绑定主群")
        return
    
    target_group = binding["target_group"]
    inactive_months = binding["inactive_months"]
    whitelist = data_manager.get_whitelist(target_group)
    
    try:
        # 获取群成员列表
        member_list = await bot.get_group_member_list(group_id=int(target_group))
        
        # 计算不活跃时间阈值
        threshold_date = datetime.now() - timedelta(days=30 * inactive_months)
        
        inactive_members = []
        
        for member in member_list:
            user_id = str(member["user_id"])
            
            # 跳过白名单用户和管理员
            if user_id in whitelist or member["role"] in ["owner", "admin"]:
                continue
            
            # 检查最后发言时间
            last_sent_time = datetime.fromtimestamp(member["last_sent_time"])
            
            if last_sent_time < threshold_date:
                nickname = member.get("nickname", "")
                card = member.get("card", "")
                display_name = card if card else nickname
                inactive_members.append({
                    "user_id": user_id,
                    "display_name": display_name,
                    "last_sent_time": last_sent_time
                })
        
        if not inactive_members:
            await check_inactive.send("没有找到不活跃成员")
            return
        
        # 按最后发言时间排序
        inactive_members.sort(key=lambda x: x["last_sent_time"])
        
        # 分批发送，每批10人
        batch_size = 10
        total_batches = (len(inactive_members) + batch_size - 1) // batch_size
        
        for i in range(0, len(inactive_members), batch_size):
            batch = inactive_members[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            message = f"不活跃成员列表 ({batch_num}/{total_batches}):\n"
            message += f"不活跃判定: {inactive_months}个月\n"
            message += "=" * 20 + "\n"
            
            for member in batch:
                days_ago = (datetime.now() - member["last_sent_time"]).days
                message += f"{member['display_name']} ({member['user_id']})\n"
                message += f"最后发言: {days_ago}天前\n"
                message += "-" * 20 + "\n"
            
            await check_inactive.send(message.strip())
            
            # 如果不是最后一批，等待2-5秒
            if i + batch_size < len(inactive_members):
                await asyncio.sleep(3)  # 等待3秒
                
    except Exception as e:
        logger.error(f"获取不活跃成员失败: {e}")
        await check_inactive.send(f"获取不活跃成员失败: {str(e)}")


@add_whitelist.handle()
async def handle_add_whitelist(bot: Bot, event: GroupMessageEvent, args=CommandArg()):
    """设定白名单"""
    args_text = str(args).strip()
    if not args_text:
        await add_whitelist.send("请输入要加入白名单的QQ号")
        return
    
    current_group = str(event.group_id)
    binding = data_manager.get_binding(current_group)
    
    if not binding:
        await add_whitelist.send("当前群未绑定主群，请先绑定主群")
        return
    
    target_group = binding["target_group"]
    
    try:
        user_id = args_text
        
        # 验证用户是否在群中
        try:
            member_info = await bot.get_group_member_info(
                group_id=int(target_group),
                user_id=int(user_id)
            )
        except Exception:
            await add_whitelist.send(f"用户 {user_id} 不在目标群中")
            return
        
        data_manager.add_whitelist(target_group, user_id)
        
        nickname = member_info.get("nickname", "")
        card = member_info.get("card", "")
        display_name = card if card else nickname
        
        await add_whitelist.send(f"已将 {display_name}({user_id}) 加入白名单")
        
    except ValueError:
        await add_whitelist.send("请输入有效的QQ号")


@remove_inactive.handle()
async def handle_remove_inactive(bot: Bot, event: GroupMessageEvent):
    """删除不活跃成员"""
    current_group = str(event.group_id)
    binding = data_manager.get_binding(current_group)
    
    if not binding:
        await remove_inactive.send("当前群未绑定主群，请先绑定主群")
        return
    
    target_group = binding["target_group"]
    inactive_months = binding["inactive_months"]
    whitelist = data_manager.get_whitelist(target_group)
    
    try:
        # 获取群成员列表
        member_list = await bot.get_group_member_list(group_id=int(target_group))
        
        # 计算不活跃时间阈值
        threshold_date = datetime.now() - timedelta(days=30 * inactive_months)
        
        removed_count = 0
        failed_count = 0
        
        for member in member_list:
            user_id = str(member["user_id"])
            
            # 跳过白名单用户和管理员
            if user_id in whitelist or member["role"] in ["owner", "admin"]:
                continue
            
            # 检查最后发言时间
            last_sent_time = datetime.fromtimestamp(member["last_sent_time"])
            
            if last_sent_time < threshold_date:
                try:
                    await bot.set_group_kick(
                        group_id=int(target_group),
                        user_id=int(user_id),
                        reject_add_request=False
                    )
                    removed_count += 1
                    await asyncio.sleep(1)  # 避免操作过快
                except Exception as e:
                    logger.error(f"踢出用户 {user_id} 失败: {e}")
                    failed_count += 1
        
        message = f"删除不活跃成员完成\n"
        message += f"成功删除: {removed_count} 人\n"
        if failed_count > 0:
            message += f"删除失败: {failed_count} 人"
        
        await remove_inactive.send(message)
        
    except Exception as e:
        logger.error(f"删除不活跃成员失败: {e}")
        await remove_inactive.send(f"删除不活跃成员失败: {str(e)}")

@remove_whitelist.handle()
async def handle_remove_whitelist(bot: Bot, event: GroupMessageEvent, args=CommandArg()):
    """删除白名单"""
    args_text = str(args).strip()
    if not args_text:
        await remove_whitelist.send("请输入要从白名单删除的QQ号")
        return
    
    current_group = str(event.group_id)
    binding = data_manager.get_binding(current_group)
    
    if not binding:
        await remove_whitelist.send("当前群未绑定主群，请先绑定主群")
        return
    
    target_group = binding["target_group"]
    
    try:
        user_id = args_text
        
        # 检查用户是否在白名单中
        whitelist = data_manager.get_whitelist(target_group)
        if user_id not in whitelist:
            await remove_whitelist.send(f"用户 {user_id} 不在白名单中")
            return
        
        # 从白名单中移除
        data_manager.data["whitelist"][target_group].discard(user_id)
        data_manager.save_data()
        
        # 尝试获取用户信息用于显示
        try:
            member_info = await bot.get_group_member_info(
                group_id=int(target_group),
                user_id=int(user_id)
            )
            nickname = member_info.get("nickname", "")
            card = member_info.get("card", "")
            display_name = card if card else nickname
            await remove_whitelist.send(f"已将 {display_name}({user_id}) 从白名单中移除")
        except Exception:
            # 即使获取用户信息失败也要移除白名单
            await remove_whitelist.send(f"已将用户 {user_id} 从白名单中移除")
        
    except ValueError:
        await remove_whitelist.send("请输入有效的QQ号")