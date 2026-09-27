# -*- coding: utf-8 -*-
from . import witholding_rate
from . import witholding_engine
from . import witholding_application
from . import account_move
from . import account_payment

# The PPh 21 payslip hook moved to ee_gap/custom_hr_payroll_id, which owns
# hr.payslip. It used to live here behind a get_modules() guard that never
# actually worked: the manifest declared custom_hr_payroll_id as a hard
# dependency anyway, so every tenant that wanted a PPh rate had to install
# payroll. That also inverted the tier (compliance depending on ee_gap).
