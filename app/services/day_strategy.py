from dataclasses import dataclass


STRATEGIES = (
    "Глубокий фокус", "Чередование категорий", "Быстрый старт",
    "Сбалансированный режим", "Щадящий режим",
)


@dataclass(frozen=True)
class StrategyRecommendation:
    strategies: tuple[str, str]
    explanation: str


def recommend_strategies(*, brain_energy: int, concentration: int, mental_fatigue: int,
                         physical_energy: int, desired_day_mode: str,
                         alternate_categories: bool | None) -> StrategyRecommendation:
    if desired_day_mode in {"🛋 Восстановительный", "🌿 Спокойный"} or brain_energy <= 3 or mental_fatigue >= 8:
        primary, secondary = "Щадящий режим", "Быстрый старт"
        explanation = "Низкий ресурс или выбранный спокойный режим: начнём бережно и не будем перегружать день."
    elif desired_day_mode in {"🎯 Сфокусированный", "🚀 Проектный"} and brain_energy >= 6 and concentration >= 6:
        primary, secondary = "Глубокий фокус", "Сбалансированный режим"
        explanation = "Есть достаточно ресурса для важной сложной задачи в начале дня."
    elif brain_energy <= 5 or concentration <= 4 or mental_fatigue >= 6:
        primary, secondary = "Быстрый старт", "Сбалансированный режим"
        explanation = "Ресурс ограничен: короткий завершённый шаг поможет включиться без перегруза."
    else:
        primary, secondary = "Сбалансированный режим", "Глубокий фокус"
        explanation = "Состояние ровное: подойдёт устойчивый план с главной задачей и сменой нагрузки."
    if alternate_categories is True:
        secondary = "Чередование категорий"
        explanation += " Вы выбрали чередование категорий, поэтому оно включено в рекомендации."
    return StrategyRecommendation((primary, secondary), explanation)
