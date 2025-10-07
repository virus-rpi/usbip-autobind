import json
import logging
import os


class PersistentDict(dict):
    def __init__(self, save_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_callback = save_callback

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.save_callback()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.save_callback()

    def update(self, m, /, **kwargs):
        super().update(m, **kwargs)
        self.save_callback()

    def pop(self, *args, **kwargs):
        result = super().pop(*args, **kwargs)
        self.save_callback()
        return result

    def clear(self):
        super().clear()
        self.save_callback()


class AssignmentManager:
    def __init__(self, assignments_file):
        self.logger = logging.getLogger("usbip-host-autobind")
        self.assignments_file = assignments_file
        self.assign_all_client_id: str = "none"
        self.device_assignments: dict[str, str] = PersistentDict(self.save_assignments)
        self.load_assignments()

    def save_assignments(self):
        try:
            tmp_file = self.assignments_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump({
                    "assign_all_client_id": self.assign_all_client_id,
                    "device_assignments": dict(self.device_assignments)
                }, f)
            os.replace(tmp_file, self.assignments_file)
        except Exception as e:
            self.logger.warning(f"Failed to save assignments: {e}")

    def load_assignments(self):
        try:
            with open(self.assignments_file, "r") as f:
                data = json.load(f)
                self.assign_all_client_id = data.get("assign_all_client_id")
                self.device_assignments.clear()
                self.device_assignments.update(data.get("device_assignments", {}))
            self.logger.info(f"Loaded assignments from {self.assignments_file}")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"Failed to load assignments: {e}")

    def set_assignment(self, bus_id, client_id):
        self.device_assignments[bus_id] = client_id

    def get_assignment(self, bus_id):
        return self.device_assignments.get(bus_id)

    def remove_assignment(self, bus_id):
        self.device_assignments.pop(bus_id, None)

    def set_assign_all(self, client_id):
        self.assign_all_client_id = client_id
        self.save_assignments()

    def clear_assignments(self):
        self.device_assignments.clear()
        self.assign_all_client_id = None
        self.save_assignments()
