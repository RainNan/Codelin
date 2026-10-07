from langgraph.graph import MessagesState


class CodelinState(MessagesState):
    """MessagesState 自带 messages
    messages: Annotated[list[AnyMessage], add_messages]

    扩展字段：
    - workspace: 本会话工作区绝对路径（工具注入用）
    - approval_decision: 危险操作的人工审批结果
    """
    workspace: str
    approval_decision: str | None = None