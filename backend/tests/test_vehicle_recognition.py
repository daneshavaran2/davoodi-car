import unittest
from vehicle_recognition import recognize_vehicle

class VehicleRecognitionTests(unittest.TestCase):
    def test_fidelity_exact(self):
        r=recognize_vehicle("ماشین فیدلیتی مدل ۱۴۰۲")
        self.assertEqual(r["model"],"فیدلیتی")
        self.assertTrue(r["requires_confirmation"])

    def test_fidelity_voice_typo(self):
        r=recognize_vehicle("خودرو فیتیلی")
        self.assertEqual(r["model"],"فیدلیتی")
        self.assertEqual(r["manufacturer"],"بهمن موتور")

    def test_unknown(self):
        r=recognize_vehicle("سلام لطفا قیمت را بگو")
        self.assertEqual(r["status"],"unknown")

    def test_blank(self):
        self.assertEqual(recognize_vehicle(" ")["status"],"missing")

if __name__=="__main__":unittest.main()
