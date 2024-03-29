from early_stopping.constants import IMPROVE, SAFE, STOP
from early_stopping.early_stopping import EarlyStopping


class PlateauEarlyStopping(EarlyStopping):
    def __init__(self, patience=10, plateau_patience=20, threshold=0.02):
        self.patience = patience
        self.plateau_patience = plateau_patience
        self.threshold = threshold
        self.reset()
    
    def reset(self):
        self.wait = 0
        self.best_metric = None
        self.feats = []
        self.plateau_count = 0

    def update_metric(self, new_metric_value):
        if self.best_metric is None or new_metric_value > self.best_metric:
            # Improvement
            self.best_metric = new_metric_value
            self.wait = 0
            self.plateau_count = 0
            return IMPROVE  # Continue training
        elif self.best_metric - self.threshold <= new_metric_value <= self.best_metric + self.threshold:
            # Plateau
            self.wait += 1
            self.plateau_count += 1
            if self.plateau_count >= self.plateau_patience:
                # print(f"Stopping due to plateau in metric. Plateau count: {self.plateau_count}")
                return STOP  # Stop training
            return SAFE  # Continue training
        else:
            # Worsening
            self.wait += 1
            self.plateau_count = 0
            if self.wait >= self.patience:
                # print(f"Stopping due to lack of improvement. Patience exceeded: {self.wait}")
                return STOP  # Stop training
            return SAFE  # Continue training
