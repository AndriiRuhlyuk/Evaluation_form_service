from django.test import TestCase

from topic.models import Topic


class TopicModelTest(TestCase):
    def test_create_topic(self):
        topic = Topic.objects.create(name="DB", description="About DBs")
        self.assertEqual(str(topic), "DB")
        self.assertTrue(topic.is_active)
