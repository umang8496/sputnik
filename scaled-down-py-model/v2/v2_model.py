"""MiniLLM v2: the v1 architecture packaged as an importable module.

Written by v2_builder.ipynb (section 06). Imported by the notebook and by v2_train.py.
"""
import torch, torch.nn as nn, torch.nn.functional as F

def rope(t):
    """Rotary position embedding over (batch, head, position, field)."""
    T, D = t.shape[-2], t.shape[-1]
    half = D // 2
    freqs = 1.0 / (10000 ** (torch.arange(half, device=t.device) / half))   # one rotation speed per field pair
    ang = torch.arange(T, device=t.device)[:, None] * freqs[None, :]        # (T, half) angles
    t1, t2 = t[..., :half], t[..., half:]
    # 2-D rotation of each (t1, t2) pair by its position-dependent angle
    return torch.cat([t1 * ang.cos() - t2 * ang.sin(), t1 * ang.sin() + t2 * ang.cos()], dim=-1)

class Block(nn.Module):                                   # one layer: Mix + Refine
    def __init__(self, width, heads, inner):
        super().__init__()
        self.heads = heads
        self.norm1, self.norm2 = nn.RMSNorm(width), nn.RMSNorm(width)
        self.Wq, self.Wk, self.Wv, self.Wo = [nn.Linear(width, width, bias=False) for _ in range(4)]   # attention tables
        self.Up, self.Down = nn.Linear(width, inner, bias=False), nn.Linear(inner, width, bias=False)  # feed-forward tables

    def forward(self, g):
        B, T, W = g.shape
        h = self.norm1(g)                                                 # pre-norm
        sp = lambda t: t.view(B, T, self.heads, W // self.heads).transpose(1, 2)   # split into heads
        q, k, v = sp(self.Wq(h)), sp(self.Wk(h)), sp(self.Wv(h))
        m = F.scaled_dot_product_attention(rope(q), rope(k), v, is_causal=True)    # causal attention
        g = g + self.Wo(m.transpose(1, 2).reshape(B, T, W))      # Mix + residual
        return g + self.Down(F.gelu(self.Up(self.norm2(g))))      # Refine + residual

class MiniLLM(nn.Module):
    def __init__(self, vocab, width, layers, heads, inner, seq):
        super().__init__()
        self.seq = seq                                            # context window, kept for generation
        self.emb = nn.Embedding(vocab, width)                     # Embedding TABLE
        self.blocks = nn.ModuleList([Block(width, heads, inner) for _ in range(layers)])
        self.norm = nn.RMSNorm(width)                             # final norm
        self.out = nn.Linear(width, vocab, bias=False)            # Output TABLE
        self.apply(self._init)                                    # new in v2: small initial weights

    @staticmethod
    def _init(m):
        # N(0, 0.02) for every weight table (GPT-2 style): first predictions stay
        # close to uniform, so the starting loss is ~ln(vocab) and early steps are stable
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, std=0.02)

    def forward(self, ids):
        g = self.emb(ids)                                         # IDs -> grid
        for b in self.blocks:
            g = b(g)
        return self.out(self.norm(g))                             # logits: (batch, seq, vocab)
