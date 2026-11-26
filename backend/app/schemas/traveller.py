"""The people travelling."""
from typing import TypedDict


class GroupMember(TypedDict):
    name: str
    likes: list[str]
    avoid: list[str]


class GroupMemberReport(GroupMember):
    """How well the finished plan serves one traveller."""
    matched: list[str]
    conflicts: list[str]
    activities: int
