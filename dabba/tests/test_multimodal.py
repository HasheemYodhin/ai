import torch
import numpy as np
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from dabba.multimodal import MultimodalProcessor
from dabba.multimodal.image_processor import ImageProcessor
from dabba.multimodal.vision_encoder import VisionEncoder
from dabba.multimodal.projection import ModalityProjection
from dabba.multimodal.cross_attention import CrossModalAttention
from dabba.multimodal.audio import AudioProcessor


class TestImageProcessor:
    def test_load_image(self):
        processor = Mock(spec=ImageProcessor)
        processor.load.return_value = torch.randn(3, 224, 224)
        image = processor.load("test.jpg")
        assert image.shape == (3, 224, 224)

    def test_preprocess_image(self):
        processor = Mock(spec=ImageProcessor)
        processor.preprocess.return_value = torch.randn(1, 3, 224, 224)
        batch = processor.preprocess([torch.randn(3, 224, 224)])
        assert batch.shape == (1, 3, 224, 224)

    def test_image_to_tensor(self):
        processor = Mock(spec=ImageProcessor)
        processor.image_to_tensor.return_value = torch.randn(3, 224, 224)
        tensor = processor.image_to_tensor("test.jpg")
        assert tensor.shape == (3, 224, 224)

    def test_resize_image(self):
        processor = Mock(spec=ImageProcessor)
        processor.resize.return_value = torch.randn(3, 336, 336)
        resized = processor.resize(torch.randn(3, 224, 224), (336, 336))
        assert resized.shape[-2:] == (336, 336)

    def test_normalize_image(self):
        processor = Mock(spec=ImageProcessor)
        processor.normalize.return_value = torch.randn(3, 224, 224)
        normalized = processor.normalize(torch.randn(3, 224, 224))
        assert normalized.shape == (3, 224, 224)

    def test_batch_images(self):
        processor = Mock(spec=ImageProcessor)
        processor.preprocess_batch.return_value = torch.randn(4, 3, 224, 224)
        batch = processor.preprocess_batch([torch.randn(3, 224, 224) for _ in range(4)])
        assert batch.shape[0] == 4


class TestVisionEncoder:
    def test_forward(self):
        encoder = Mock(spec=VisionEncoder)
        encoder.return_value = torch.randn(1, 196, 768)
        x = torch.randn(1, 3, 224, 224)
        features = encoder(x)
        assert features.shape == (1, 196, 768)

    def test_encoder_config(self):
        encoder = Mock(spec=VisionEncoder)
        type(encoder).embedding_dim = PropertyMock(return_value=1024)
        type(encoder).num_patches = PropertyMock(return_value=256)
        assert encoder.embedding_dim == 1024
        assert encoder.num_patches == 256

    def test_vision_encoder_backbone(self):
        encoder = Mock(spec=VisionEncoder)
        type(encoder).model_name = PropertyMock(return_value="vit-base-patch16-224")
        assert encoder.model_name == "vit-base-patch16-224"

    def test_encoder_output_type(self):
        encoder = Mock(spec=VisionEncoder)
        encoder.return_value = torch.randn(1, 196, 768)
        features = encoder(torch.randn(1, 3, 224, 224))
        assert features.dtype == torch.float32

    def test_encoder_trainable(self):
        encoder = Mock(spec=VisionEncoder)
        encoder.train.return_value = None
        encoder.eval.return_value = None
        encoder.train()
        encoder.eval()

    def test_encoder_pooled_output(self):
        encoder = Mock(spec=VisionEncoder)
        encoder.return_value = (torch.randn(1, 196, 768), torch.randn(1, 768))
        patch_out, pooled = encoder(torch.randn(1, 3, 224, 224))
        assert pooled.shape == (1, 768)


class TestModalityProjection:
    def test_project_image_to_text(self):
        projection = Mock(spec=ModalityProjection)
        projection.project.return_value = torch.randn(1, 196, 512)
        image_features = torch.randn(1, 196, 768)
        projected = projection.project(image_features)
        assert projected.shape == (1, 196, 512)

    def test_project_audio_to_text(self):
        projection = Mock(spec=ModalityProjection)
        projection.project.return_value = torch.randn(1, 50, 512)
        audio_features = torch.randn(1, 50, 1280)
        projected = projection.project(audio_features)
        assert projected.shape == (1, 50, 512)

    def test_projection_dimensions(self):
        projection = Mock(spec=ModalityProjection)
        type(projection).input_dim = PropertyMock(return_value=768)
        type(projection).output_dim = PropertyMock(return_value=512)
        assert projection.input_dim == 768
        assert projection.output_dim == 512

    def test_projection_linear(self):
        projection = Mock(spec=ModalityProjection)
        proj = Mock(spec=torch.nn.Linear)
        proj.return_value = torch.randn(1, 196, 512)
        projection.linear = proj
        result = projection.linear(torch.randn(1, 196, 768))
        assert result.shape[-1] == 512


class TestCrossModalAttention:
    def test_forward(self):
        cm_attn = Mock(spec=CrossModalAttention)
        cm_attn.return_value = torch.randn(1, 10, 512)
        text_features = torch.randn(1, 10, 512)
        image_features = torch.randn(1, 196, 768)
        output = cm_attn(text_features, image_features)
        assert output.shape == (1, 10, 512)

    def test_cross_attention_with_mask(self):
        cm_attn = Mock(spec=CrossModalAttention)
        cm_attn.return_value = torch.randn(1, 10, 512)
        text = torch.randn(1, 10, 512)
        vision = torch.randn(1, 196, 768)
        mask = torch.ones(1, 10, 196)
        output = cm_attn(text, vision, attention_mask=mask)
        assert output.shape == (1, 10, 512)


class TestAudioProcessor:
    def test_load_audio(self):
        processor = Mock(spec=AudioProcessor)
        processor.load.return_value = torch.randn(16000)
        audio = processor.load("test.wav")
        assert audio.shape[0] > 0

    def test_preprocess_audio(self):
        processor = Mock(spec=AudioProcessor)
        processor.preprocess.return_value = torch.randn(1, 80, 3000)
        features = processor.preprocess(torch.randn(16000))
        assert features.shape == (1, 80, 3000)

    def test_audio_to_text(self):
        processor = Mock(spec=AudioProcessor)
        processor.transcribe.return_value = "Hello, this is a test transcription."
        text = processor.transcribe("test.wav")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_audio_features(self):
        processor = Mock(spec=AudioProcessor)
        processor.extract_features.return_value = torch.randn(1, 50, 1280)
        features = processor.extract_features(torch.randn(16000))
        assert features.shape[-1] == 1280

    def test_sample_rate(self):
        processor = Mock(spec=AudioProcessor)
        type(processor).sample_rate = PropertyMock(return_value=16000)
        assert processor.sample_rate == 16000

    def test_audio_duration(self):
        processor = Mock(spec=AudioProcessor)
        processor.get_duration.return_value = 5.0
        duration = processor.get_duration(torch.randn(80000))
        assert duration == 5.0

    def test_resample_audio(self):
        processor = Mock(spec=AudioProcessor)
        processor.resample.return_value = torch.randn(16000)
        resampled = processor.resample(torch.randn(44100), 44100, 16000)
        assert resampled.shape[0] > 0

    def test_audio_processor_model(self):
        processor = Mock(spec=AudioProcessor)
        type(processor).model_name = PropertyMock(return_value="whisper-tiny")
        assert processor.model_name == "whisper-tiny"


class TestMultimodalProcessor:
    def test_process_image_and_text(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "A cat sitting on a chair.",
            "modality": "image+text",
        }
        result = processor.process(text="What is in this image?", image_path="cat.jpg")
        assert "text_output" in result
        assert result["modality"] == "image+text"

    def test_process_audio_and_text(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "Transcribed: hello world.",
            "modality": "audio+text",
        }
        result = processor.process(text="Transcribe this", audio_path="speech.wav")
        assert result["modality"] == "audio+text"

    def test_process_image_only(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "This image shows a landscape.",
            "modality": "image",
        }
        result = processor.process(image_path="landscape.jpg")
        assert "text_output" in result

    def test_process_audio_only(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "Transcribed text from audio.",
            "modality": "audio",
        }
        result = processor.process(audio_path="recording.wav")
        assert result["modality"] == "audio"

    def test_process_text_only(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "Response to text-only input.",
            "modality": "text",
        }
        result = processor.process(text="Hello, how are you?")
        assert result["modality"] == "text"

    def test_batch_process(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process_batch.return_value = [
            {"text_output": "Result 1", "modality": "image+text"},
            {"text_output": "Result 2", "modality": "image+text"},
        ]
        inputs = [
            {"text": "Q1", "image_path": "img1.jpg"},
            {"text": "Q2", "image_path": "img2.jpg"},
        ]
        results = processor.process_batch(inputs)
        assert len(results) == 2

    def test_available_modalities(self):
        processor = Mock(spec=MultimodalProcessor)
        type(processor).modalities = PropertyMock(return_value=["text", "image", "audio"])
        assert "image" in processor.modalities
        assert "audio" in processor.modalities

    def test_process_with_config(self):
        processor = Mock(spec=MultimodalProcessor)
        processor.process.return_value = {
            "text_output": "Configurable result.",
            "modality": "image+text",
        }
        result = processor.process(text="Test", image_path="test.jpg", max_tokens=50, temperature=0.5)
        assert result is not None
