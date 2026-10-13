from langgraph.graph import MessagesState
from typing import NotRequired
from typing import TypedDict

class CodelinState(MessagesState):
    """Agent 各节点共享的状态结构，运行时以字典形式访问。

    继承的 messages 字段类型为 Annotated[list[AnyMessage], add_messages]：
    保存用户、AI 和工具消息；节点返回新消息时，由 add_messages 合并历史，
    通常追加新消息，同 ID 的消息则更新原消息。

    其他字段未声明合并函数，节点返回对应字段时覆盖旧值，未返回则保留。
    配置 checkpointer 后，LangGraph 会持久化状态，用于继续对话和恢复审批。
    NotRequired 表示字典可以缺少该键；str | None 表示键的值可以为空。
    类型声明不会自动补齐字典字段，初始值应由输入或节点更新提供。
    """

    # 工作区根目录的绝对路径
    # 独立对话尚未关联工作区时为 None；子目录由工具的 path 参数指定。
    workspace: str | None

    # 人工审批结果："approved" / "rejected"；工具执行结束后重置为 None。
    approval_decision: str | None = None

    # 当前聊天会话的数据库 ID, checkpoint 的 thread_id
    session_id: str

    # 工作区 ID
    workspace_id: NotRequired[str | None]
    # Agent 自动创建工作区后，需要通知前端的信息
    workspace_created: NotRequired[dict | None]

    # 本次工具执行产生的文件或工作区变更
    file_changes: NotRequired[list[dict]]
