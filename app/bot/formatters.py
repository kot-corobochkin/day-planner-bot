from app.models.task import TaskStatus
from app.services.planning_service import PlanWithTasks
from app.services.task_prioritization import order_tasks_by_priority


def format_plan(plan_with_tasks: PlanWithTasks) -> str:
    lines = [
        f"План на {plan_with_tasks.plan.plan_date} ({plan_with_tasks.plan.day_type}):",
        "",
    ]
    for index, assessment in enumerate(
        order_tasks_by_priority(plan_with_tasks.tasks), start=1
    ):
        task = assessment.task
        marker = "x" if task.status == TaskStatus.done else " "
        priority_marker = f" {assessment.emoji}" if assessment.emoji else ""
        lines.append(
            f"{index}. [{marker}] {task.text} - {task.status.value}{priority_marker}"
        )
    return "\n".join(lines)
