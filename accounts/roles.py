STUDENT = "student"
TEACHER = "teacher"
MAINTAINER = "maintainer"

# These three groups are reserved and managed by init_roles. They do not
# toggle is_staff or is_superuser, and class grants never imply a role.
ROLE_PERMISSIONS = {
    STUDENT: [],
    TEACHER: [
        ("classrooms", "classroom", "view_class_progress"),
        ("classrooms", "classroom", "export_class_scores"),
        ("classrooms", "classroom", "export_class_roster"),
    ],
    MAINTAINER: [
        ("accounts", "user", "maintain_accounts"),
        ("classrooms", "classroom", "maintain_class_assignments"),
    ],
}
