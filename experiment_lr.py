import pandas as pd
from sklearn.model_selection import train_test_split

# 固定随机种子，保证结果可以复现
RANDOM_STATE = 42

# 读取数据
train_df = pd.read_csv("train_data.csv")
test_df = pd.read_csv("test_data_unlabeled.csv")

X = train_df["text"].astype(str)
y = train_df["target"]
X_test = test_df["text"].astype(str)

# 将原训练集按 8:2 划分为训练集和验证集
X_train, X_val, y_train, y_val = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=RANDOM_STATE,
    stratify=y
)

print("数据划分完成")
print("原始训练数据：", len(X))
print("训练集：", len(X_train))
print("验证集：", len(X_val))
print("无标签测试集：", len(X_test))
print("训练集类别数量：", y_train.nunique())
print("验证集类别数量：", y_val.nunique())



from sklearn.feature_extraction.text import TfidfVectorizer

# 创建 TF-IDF 特征提取器
vectorizer = TfidfVectorizer(
    lowercase=True,          # 转换为小写
    stop_words="english",    # 去除英文停用词
    max_features=20000,      # 最多保留两万个特征
    ngram_range=(1, 2),      # 同时考虑单词和双词组合
    min_df=2,                # 至少在两篇文本中出现
    sublinear_tf=True        # 使用对数缩放词频
)

# 只能在训练集上学习词表，避免验证集信息泄漏
X_train_tfidf = vectorizer.fit_transform(X_train)

# 验证集只使用训练集得到的词表进行转换
X_val_tfidf = vectorizer.transform(X_val)

print("\nTF-IDF 特征提取完成")
print("训练集特征矩阵：", X_train_tfidf.shape)
print("验证集特征矩阵：", X_val_tfidf.shape)



from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

lr_results = []

for c_value in [0.1, 1.0, 5.0, 10.0, 15.0, 20.0, 30.0, 100.0]:
    print(f"\n开始训练逻辑回归，C={c_value}", flush=True)

    model = LogisticRegression(
        C=c_value,
        max_iter=2000,
        random_state=RANDOM_STATE
    )

    model.fit(X_train_tfidf, y_train)
    y_pred = model.predict(X_val_tfidf)

    accuracy = accuracy_score(y_val, y_pred)
    macro_f1 = f1_score(
        y_val, y_pred, average="macro", zero_division=0
    )

    lr_results.append({
        "model": "LogisticRegression",
        "C": c_value,
        "accuracy": accuracy,
        "macro_f1": macro_f1
    })

    print(f"准确率：{accuracy:.4f}")
    print(f"Macro-F1：{macro_f1:.4f}")

pd.DataFrame(lr_results).to_csv(
    "lr_results.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n逻辑回归实验完成，结果已保存到 lr_results.csv")