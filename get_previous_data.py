class GetPreviousData:
    def _get_previous_year_month(year: int, month: int):
        if month == 1:
            return year - 1, 12
        return year, month - 1
