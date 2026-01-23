class MkRequests:
    def __init__(self,shift_requests_primary,shift_requests_concurrent,shift_results_oncall,hope_list,staff_list_pass):
        self.shift_requests_primary = shift_requests_primary
        self.shift_requests_concurrent = shift_requests_concurrent
        self.shift_results_oncall = shift_results_oncall
        self.hope_list = hope_list
        self.staff_list_pass = staff_list_pass
    
    def primary_requests(self):
        #専属業務の希望・制約条件・休み希望をここで追加
        
        # スタッフ６に6日から23日まで8:DIを割り当て
        for day in range(6, 24):
            for i, request in enumerate(self.shift_requests_primary):
                if request[0] == 6 and request[1] == day:
                    self.shift_requests_primary[i][2] = 8
                    break
        
        return self.shift_requests_primary
    
    def concurrent_requests(self):
        #兼務業務の希望・制約条件をここで追加
        return self.shift_requests_concurrent
    
    def oncall_requests(self):
        #当直業務の希望・制約条件をここで追加
        #当直不可、当直希望日の反映
        return self.shift_results_oncall
    
    def __call__(self):
        self.primary_requests()
        self.concurrent_requests()
        self.oncall_requests()