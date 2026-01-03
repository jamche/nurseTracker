import unittest

from utils.job_type import infer_job_type


class TestJobTypeInference(unittest.TestCase):
    def test_infers_part_time_temporary(self) -> None:
        jt = infer_job_type(
            job_title="Registered Nurse, Operating Room - Part Time Temporary (Until Approx. May, 2026)",
            current_job_type="Full-Time Permanent",
        )
        self.assertEqual(jt, "Part-Time Temporary")

    def test_infers_ptt(self) -> None:
        jt = infer_job_type(
            job_title="Registered Nurse (RN),Endoscopy - PTT(J1225-0381)",
            current_job_type="Full-Time Permanent",
        )
        self.assertEqual(jt, "Part-Time")

    def test_infers_ftt(self) -> None:
        jt = infer_job_type(
            job_title="Registered Nurse - NICU, FTT(J1225-0157)",
            current_job_type="Full-Time Permanent",
        )
        self.assertEqual(jt, "Full-Time")

    def test_falls_back_when_no_signal(self) -> None:
        jt = infer_job_type(job_title="2500003624 - Registered Nurse", current_job_type="Full-Time Permanent")
        self.assertEqual(jt, "Full-Time Permanent")

