from django.urls import path
from . import views

urlpatterns = [
    path("", views.workspace),
    path("circuit", views.circuit_page),
    # 学生战绩：完成题目数、班级排名、通过的题目与成就。
    path("profile", views.profile_page),
    # 代码题：写表达式、服务端判分、源码进存档。
    path("code", views.code_page),
    # 云端存档：每章状态、成绩、电路/代码存档摘要。
    path("saves", views.saves_page),
    # 关卡页：剧情演完「前往关卡」落到这里，level_id 是电路谜题 id
    path("level/<str:level_id>", views.level_page),
    # 全屏剧情页：宿主（大地图/章节小地图）点 NPC 后跳到 /game/story/<chapterId>/<npcId>
    path("story/<str:chapter_id>/<str:npc_id>", views.story_page),
    path("api/chapters", views.chapters),
    path("api/chapters/<str:chapter_id>/progress", views.progress),
    path("api/chapters/<str:chapter_id>/action", views.action),
    path("api/teacher/classes/<str:class_id>/scores", views.teacher_scores),
    path("api/teacher/classes/<str:class_id>/scores.csv", views.teacher_scores_csv),
    # 电路谜题
    path("api/circuit/story", views.circuit_story),
    path("api/circuit/puzzles", views.circuit_puzzles),
    path("api/circuit/puzzles/<str:puzzle_id>", views.circuit_puzzle),
    path("api/circuit/puzzles/<str:puzzle_id>/grade", views.circuit_grade),
]
