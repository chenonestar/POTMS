"""确保测试可从仓库根目录导入应用模块。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def make_valid_id(birth: str = "19900101", seq: str = "213") -> str:
    """按国标校验位算法生成一个合法 18 位身份证号（供多个测试复用）。

    seq 末位奇偶决定性别：奇→男，偶→女。默认 213（男）。
    """
    body = "110101" + birth + seq
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check = "10X98765432"
    s = sum(int(body[i]) * weights[i] for i in range(17))
    return body + check[s % 11]
