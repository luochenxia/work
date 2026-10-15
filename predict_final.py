from pathlib import Path
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

# 使用脚本所在文件夹，避免运行位置不同导致找不到数据
DATA_DIR = Path(__file__).resolve().parent

train_df = pd.read_csv(DATA_DIR / "train_data.csv")
test_df = pd.read_csv(DATA_DIR / "test_data_unlabeled.csv")

X = train_df["text"].astype(str)
y = train_df["target"]
X_test = test_df["text"].astype(str)

# 保持与验证实验相同的特征配置
vectorizer = TfidfVectorizer(
    lowercase=True,
    stop_words="english",
    max_features=20000,
    ngram_range=(1, 2),
    min_df=2,
    sublinear_tf=True
)

print("正在提取全部训练数据的特征……", flush=True)
X_tfidf = vectorizer.fit_transform(X)
X_test_tfidf = vectorizer.transform(X_test)

# 使用验证集上选出的最佳参数
model = LogisticRegression(
    C=20.0,
    max_iter=2000,
    random_state=42
)

print("正在训练最终模型……", flush=True)
model.fit(X_tfidf, y)

predictions = model.predict(X_test_tfidf)

# 保持测试集原始行顺序；单列、无表头、无索引
output_path = DATA_DIR / "prediction.csv"
pd.DataFrame(predictions).to_csv(
    output_path,
    index=False,
    header=False
)

# 检查保存后的格式
saved = pd.read_csv(output_path, header=None)
assert saved.shape == (len(test_df), 1)
assert saved[0].isin(y.unique()).all()

print("预测文件生成成功：", output_path)
print("预测行数：", len(saved))
print("前五条预测：", saved[0].head().tolist())