from abc import ABC, abstractmethod
from ortools.sat.python import cp_model

class BaseConstraint(ABC):
    """制約条件の基底クラス"""
    def __init__(self, model: cp_model.CpModel, optimizer):
        self.model = model
        self.optimizer = optimizer
        self.staff = optimizer.staff
        self.days = optimizer.days
        self.shifts = optimizer.shifts
        self.concurrent_shifts = optimizer.concurrent_shifts
        self.hope_list = optimizer.hope_list
        self.primary_sections = optimizer.primary_sections #TODO：役職。会議等で決まる出勤希望リストを別で作成する必要なケければ不要
        self.concurrent_sections = optimizer.concurrent_sections #TODO：役職。会議等で決まる出勤希望リストを別で作成する必要なケければ不要
        self.required_nun = optimizer.required_num
        self.concurrent_sections = optimizer.concurrent_sections
        self.night_shifts = optimizer.night_shifts
        
        
    @abstractmethod
    def apply(self):
        """制約を適用する"""
        pass