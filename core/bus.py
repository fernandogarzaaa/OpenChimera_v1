class EventBus:
    def publish(self, topic, data):
        print(f"[{topic}] {data}")
