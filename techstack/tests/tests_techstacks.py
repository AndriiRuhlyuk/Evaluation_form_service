from django.test import TestCase

from techstack.models import TechStack


class TechStackModelTest(TestCase):
    def test_create_techstack(self):
        tech = TechStack.objects.create(
            name="Python", description="Programming language"
        )
        self.assertEqual(str(tech), "Python")
        self.assertTrue(tech.is_active)
