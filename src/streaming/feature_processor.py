"""
Real-time Feature Processing with kafka-python
Consumes user interactions from Kafka and updates user/item features in Redis.
"""

import asyncio
import json
import time
from typing import Any, Dict

import numpy as np
import pandas as pd
import redis
import structlog
import yaml
from kafka import KafkaConsumer
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

logger = structlog.get_logger()

FEATURE_COLUMNS = [
    "rating",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
]


class FeatureProcessor:
    """Consumes Kafka interaction events, engineers features, and persists to Redis."""

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        kafka_cfg = self.config["streaming"]["kafka"]
        self.consumer = KafkaConsumer(
            "user_interactions",
            bootstrap_servers=kafka_cfg["bootstrap_servers"],
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            group_id="feature-processor",
        )

        redis_cfg = self.config.get("redis", {})
        self.redis = redis.Redis(
            host=redis_cfg.get("host", "localhost"),
            port=redis_cfg.get("port", 6379),
            db=0,
            decode_responses=True,
        )

        self.scaler = StandardScaler()
        self.pca = PCA(n_components=max(1, int(len(FEATURE_COLUMNS) * 0.33)))
        self._pipeline_fitted = False

        dim_cfg = self.config.get("features", {}).get("dimensionality_reduction", {})
        self.target_variance = dim_cfg.get("target_variance", 0.95)
        self.max_components = dim_cfg.get("max_components", 5)

        self.feature_stats: Dict[str, Any] = {}
        self._batch_size = 100

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_feature_stats(self) -> Dict[str, Any]:
        return {
            "feature_stats": self.feature_stats,
            "pipeline_trained": self._pipeline_fitted,
            "target_variance": self.target_variance,
            "dimensionality_reduction": 0.67,
        }

    async def start_streaming(self):
        logger.info("Starting feature processing stream...")
        try:
            await asyncio.to_thread(self._consume_loop)
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _consume_loop(self):
        buffer = []
        for msg in self.consumer:
            buffer.append(msg.value)
            if len(buffer) >= self._batch_size:
                self._process_batch(buffer)
                buffer = []

    def _process_batch(self, records: list):
        df = pd.DataFrame(records)
        if df.empty:
            return

        df = self._add_derived_features(df)
        self._update_user_profiles(df)
        self._update_item_features(df)
        self._fit_or_transform_pipeline(df)
        self._update_feature_stats(df)
        logger.info(f"Processed batch of {len(df)} interactions")

    def _add_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "timestamp" not in df.columns:
            df["timestamp"] = time.time()
        ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df["hour_of_day"] = ts.dt.hour
        df["day_of_week"] = ts.dt.dayofweek
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        return df

    def _update_user_profiles(self, df: pd.DataFrame):
        try:
            profile = (
                df.groupby("user_id")
                .agg(
                    avg_rating=("rating", "mean"),
                    interaction_count=("rating", "count"),
                    last_interaction=("timestamp", "max"),
                )
                .reset_index()
            )
            pipe = self.redis.pipeline()
            for _, row in profile.iterrows():
                key = f"user:{int(row['user_id'])}:profile"
                pipe.hset(
                    key,
                    mapping={
                        "avg_rating": round(float(row["avg_rating"]), 4),
                        "interaction_count": int(row["interaction_count"]),
                        "last_interaction": float(row["last_interaction"]),
                    },
                )
            pipe.execute()
        except Exception as e:
            logger.error(f"Error updating user profiles: {e}")

    def _update_item_features(self, df: pd.DataFrame):
        try:
            features = (
                df.groupby("item_id")
                .agg(
                    avg_rating=("rating", "mean"),
                    interaction_count=("rating", "count"),
                    unique_users=("user_id", "nunique"),
                )
                .reset_index()
            )
            pipe = self.redis.pipeline()
            for _, row in features.iterrows():
                key = f"item:{int(row['item_id'])}:features"
                pipe.hset(
                    key,
                    mapping={
                        "avg_rating": round(float(row["avg_rating"]), 4),
                        "interaction_count": int(row["interaction_count"]),
                        "unique_users": int(row["unique_users"]),
                    },
                )
            pipe.execute()
        except Exception as e:
            logger.error(f"Error updating item features: {e}")

    def _fit_or_transform_pipeline(self, df: pd.DataFrame):
        try:
            cols = [c for c in FEATURE_COLUMNS if c in df.columns]
            if not cols:
                return
            X = df[cols].fillna(0).values.astype(float)
            if not self._pipeline_fitted:
                X_scaled = self.scaler.fit_transform(X)
                n_components = min(self.pca.n_components, X_scaled.shape[1], X_scaled.shape[0])
                self.pca.set_params(n_components=n_components)
                self.pca.fit(X_scaled)
                self._pipeline_fitted = True
                logger.info(
                    f"PCA fitted: {X_scaled.shape[1]} -> {n_components} dims, "
                    f"variance={self.pca.explained_variance_ratio_.sum():.3f}"
                )
        except Exception as e:
            logger.error(f"Error fitting feature pipeline: {e}")

    def _update_feature_stats(self, df: pd.DataFrame):
        try:
            cols = [c for c in FEATURE_COLUMNS if c in df.columns]
            desc = df[cols].describe()
            for col in desc.columns:
                for stat in desc.index:
                    val = desc.loc[stat, col]
                    if not np.isnan(val):
                        self.feature_stats[f"{col}_{stat}"] = round(float(val), 4)
        except Exception as e:
            logger.error(f"Error updating feature stats: {e}")


async def main():
    processor = FeatureProcessor()
    try:
        await processor.start_streaming()
    except KeyboardInterrupt:
        logger.info("Stopping feature processor...")


if __name__ == "__main__":
    asyncio.run(main())
