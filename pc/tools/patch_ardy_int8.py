"""patch_ardy_int8.py - lets ARDY load the 8-bit text encoder (voxta/Llama-3-8B-LLM2Vec-ARDY-INT8) instead of the gated bf16 one.

    python patch_ardy_int8.py "<ardy repo>\\ardy\\model\\llm2vec\\llm2vec_wrapper.py"

Why: out of the box ARDY's text encoder is McGill-NLP's LLM2Vec on top of meta-llama/Meta-Llama-3-8B-Instruct: 15.4 GB of VRAM
and a Hugging Face account with access to the gated Llama 3 repo. The INT8 build published by the Voxta team is the same encoder
with both adapters merged and quantised to 8 bit: 8 GB, no gate, cosine similarity 0.998 to the reference. VaMRT's scripts ask for
it by setting the environment variable ARDY_TEXT_ENCODER_INT8 to the repo id (ardy_to_vam.py: INT8_REPO); this patch teaches
LLM2VecEncoder to honour that variable:
  * the repo is fetched with huggingface_hub.snapshot_download so the vendored loader sees a local folder (it only reads
    llm2vec_config.json - the pooling settings - from a folder, not from a hub id)
  * no PEFT adapter is loaded (already merged), the model is placed on the GPU by device_map (an 8-bit model cannot be .to()'d)
  * config._name_or_path is forced to meta-llama/Meta-Llama-3-8B-Instruct, which selects the Llama 3 instruction template in
    prepare_for_tokenization (transformers 5 no longer serialises that field, so the saved config does not carry it)
Lynn's hand-patched wrapper (Nov 2026) did the same with two differences: it passed the hub id straight to the loader (so the
repo's llm2vec_config.json was not read - harmless, its values equal the defaults) and it never set _name_or_path, so prompts went
in WITHOUT the Llama 3 user-turn header the reference encoder uses. ARDY_TEXT_ENCODER_INT8_RAW=1 reproduces that behaviour.
Needs: pip install bitsandbytes (setup.bat does). Anchor-checked: nothing changes unless every anchor is found exactly once; the
original is kept as .bak. Unset ARDY_TEXT_ENCODER_INT8 (or run the stream with --full-encoder) and the stock path is used.
"""
import shutil
import sys
from pathlib import Path

EDITS = [
    ("load", "        self.model = LLM2Vec.from_pretrained(\n"
             "            base_model_name_or_path=base_model_name_or_path,\n"
             "            peft_model_name_or_path=peft_model_name_or_path,\n"
             "            torch_dtype=torch_dtype,\n"
             "            cache_dir=cache_dir,\n"
             "        )\n"
             "\n"
             "        env_device = os.environ.get(\"TEXT_ENCODER_DEVICE\")\n"
             "        if env_device:\n"
             "            device = env_device\n"
             "        if device == \"auto\":\n"
             "            device = \"cuda\" if torch.cuda.is_available() else \"cpu\"\n"
             "        self._device = device\n"
             "        if device is not None:\n"
             "            self.model = self.model.to(device)\n",
     "        env_device = os.environ.get(\"TEXT_ENCODER_DEVICE\")\n"
     "        if env_device:\n"
     "            device = env_device\n"
     "        if device == \"auto\":\n"
     "            device = \"cuda\" if torch.cuda.is_available() else \"cpu\"\n"
     "        self._device = device\n"
     "\n"
     "        # VaMRT: an 8-bit, adapter-merged build of the same encoder (half the VRAM, no gated repo). Set\n"
     "        # ARDY_TEXT_ENCODER_INT8=voxta/Llama-3-8B-LLM2Vec-ARDY-INT8 (or a local folder) to use it.\n"
     "        int8_repo = os.environ.get(\"ARDY_TEXT_ENCODER_INT8\")\n"
     "        if int8_repo:\n"
     "            local = int8_repo\n"
     "            if not os.path.isdir(local):\n"
     "                from huggingface_hub import snapshot_download\n"
     "                local = snapshot_download(int8_repo, cache_dir=cache_dir)\n"
     "            dev_map = {\"\": device} if device not in (None, \"cpu\") else None\n"
     "            self.model = LLM2Vec.from_pretrained(\n"
     "                base_model_name_or_path=local,\n"
     "                peft_model_name_or_path=None,\n"
     "                torch_dtype=torch_dtype,\n"
     "                cache_dir=cache_dir,\n"
     "                device_map=dev_map,\n"
     "            )\n"
     "            # the reference encoder wraps every prompt in Llama 3's user-turn header (prepare_for_tokenization keys that on\n"
     "            # this name; transformers 5 does not save it). ARDY_TEXT_ENCODER_INT8_RAW=1 skips it (the Nov 2026 hand-patched\n"
     "            # setup ran without the header and worked; set this to reproduce that exactly).\n"
     "            if not os.environ.get(\"ARDY_TEXT_ENCODER_INT8_RAW\"):\n"
     "                self.model.model.config._name_or_path = \"meta-llama/Meta-Llama-3-8B-Instruct\"\n"
     "            print(f\"[text encoder] INT8 build {int8_repo} on {device}\")\n"
     "        else:\n"
     "            self.model = LLM2Vec.from_pretrained(\n"
     "                base_model_name_or_path=base_model_name_or_path,\n"
     "                peft_model_name_or_path=peft_model_name_or_path,\n"
     "                torch_dtype=torch_dtype,\n"
     "                cache_dir=cache_dir,\n"
     "            )\n"
     "            if device is not None:\n"
     "                self.model = self.model.to(device)\n"),
    ("to", "    def to(self, device: torch.device | str | None = None, dtype: torch.dtype | None = None):\n"
           "        if device is not None and dtype is not None:\n",
     "    def to(self, device: torch.device | str | None = None, dtype: torch.dtype | None = None):\n"
     "        if os.environ.get(\"ARDY_TEXT_ENCODER_INT8\"):\n"
     "            return self   # an 8-bit model lives where bitsandbytes put it; moving or re-typing it raises\n"
     "        if device is not None and dtype is not None:\n"),
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if "ARDY_TEXT_ENCODER_INT8" in src:
        print("already patched (ARDY_TEXT_ENCODER_INT8 is handled).")
        return
    for name, anchor, _ in EDITS:
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"cannot patch: anchor '{name}' found {n} times (expected 1). The ARDY checkout differs from the one "
                             f"this patch was written for (nv-tlabs/ardy e706e27, Oct 2026). Nothing changed.")
    for _, anchor, repl in EDITS:
        src = src.replace(anchor, repl, 1)
    shutil.copy2(path, str(path) + ".bak")
    path.write_bytes((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
    print(f"patched {path} (original kept as {path.name}.bak)")


if __name__ == "__main__":
    main()
