"""Tests for TileDB integration with PyTorch Data API."""
from operator import methodcaller

import numpy as np
import pytest
import torch

from tiledb.ml.readers.pytorch import PyTorchTileDBDataLoader, TensorKind

from .utils import (
    assert_tensors_almost_equal_array,
    ingest_in_tiledb,
    parametrize_for_dataset,
    validate_tensor_generator,
)


class TestPyTorchTileDBDataLoader:
    @parametrize_for_dataset()
    def test_dataloader(
        self, tmpdir, x_spec, y_spec, batch_size, shuffle_buffer_size, num_workers
    ):
        with ingest_in_tiledb(tmpdir, x_spec) as (x_params, x_data):
            x_schema = x_params.tensor_schema
            with ingest_in_tiledb(tmpdir, y_spec) as (y_params, y_data):
                y_schema = y_params.tensor_schema
                try:
                    dataloader = PyTorchTileDBDataLoader(
                        x_params,
                        y_params,
                        shuffle_buffer_size=shuffle_buffer_size,
                        batch_size=batch_size,
                        num_workers=num_workers,
                    )
                except NotImplementedError:
                    assert num_workers and (x_spec.sparse or y_spec.sparse)
                else:
                    assert isinstance(dataloader, torch.utils.data.DataLoader)
                    validate_tensor_generator(
                        dataloader, x_schema, y_schema, x_spec, y_spec, batch_size
                    )
                    # ensure the dataloader can be iterated again
                    n1 = sum(1 for _ in dataloader)
                    assert n1 != 0
                    n2 = sum(1 for _ in dataloader)
                    assert n1 == n2

    @parametrize_for_dataset(
        x_sparse=(True,),
        non_key_dim_dtype=(np.dtype(np.int32),),
        num_workers=[0],
    )
    def test_dataloader_csr(
        self, tmpdir, x_spec, y_spec, batch_size, shuffle_buffer_size, num_workers
    ):
        tensor_kind = TensorKind.SPARSE_CSR
        with ingest_in_tiledb(tmpdir, x_spec, tensor_kind) as (x_params, x_data):
            x_schema = x_params.tensor_schema
            with ingest_in_tiledb(tmpdir, y_spec) as (y_params, y_data):
                y_schema = y_params.tensor_schema
                try:
                    dataloader = PyTorchTileDBDataLoader(
                        x_params,
                        y_params,
                        shuffle_buffer_size=shuffle_buffer_size,
                        batch_size=batch_size,
                        num_workers=num_workers,
                    )
                except ValueError as ex:
                    assert str(ex) == "Cannot generate CSR tensors for 3D array"
                    x_ndim = len(x_spec.shape)
                    assert x_ndim > 3 or x_ndim == 3 and batch_size is not None
                else:
                    assert isinstance(dataloader, torch.utils.data.DataLoader)
                    validate_tensor_generator(
                        dataloader, x_schema, y_schema, x_spec, y_spec, batch_size
                    )
                    # ensure the dataloader can be iterated again
                    n1 = sum(1 for _ in dataloader)
                    assert n1 != 0
                    n2 = sum(1 for _ in dataloader)
                    assert n1 == n2

    @parametrize_for_dataset(
        # Add one extra key on X
        x_shape=((108, 10), (108, 10, 3)),
        y_shape=((107, 5), (107, 5, 2)),
    )
    def test_unequal_num_keys(
        self, tmpdir, x_spec, y_spec, batch_size, shuffle_buffer_size, num_workers
    ):
        with ingest_in_tiledb(tmpdir, x_spec) as (x_params, x_data):
            with ingest_in_tiledb(tmpdir, y_spec) as (y_params, y_data):
                with pytest.raises(ValueError) as ex:
                    PyTorchTileDBDataLoader(
                        x_params,
                        y_params,
                        shuffle_buffer_size=shuffle_buffer_size,
                        batch_size=batch_size,
                        num_workers=num_workers,
                    )
                assert "All arrays must have the same key range" in str(ex.value)

    @parametrize_for_dataset(
        num_fields=[0],
        shuffle_buffer_size=[0],
        num_workers=[0],
    )
    def test_dataloader_order(
        self, tmpdir, x_spec, y_spec, batch_size, shuffle_buffer_size, num_workers
    ):
        """Test we can read the data in the same order as written.

        The order is guaranteed only for sequential processing (num_workers=0) and
        no shuffling (shuffle_buffer_size=0).
        """
        to_dense = methodcaller("to_dense")
        with ingest_in_tiledb(tmpdir, x_spec) as (x_params, x_data):
            x_tensor_kind = x_params.tensor_schema.kind
            with ingest_in_tiledb(tmpdir, y_spec) as (y_params, y_data):
                y_tensor_kind = y_params.tensor_schema.kind
                dataloader = PyTorchTileDBDataLoader(
                    x_params,
                    y_params,
                    shuffle_buffer_size=shuffle_buffer_size,
                    batch_size=batch_size,
                    num_workers=num_workers,
                )
                # since num_fields is 0, fields are all the array attributes of each array
                # the first item of each batch corresponds to the first attribute (="data")
                x_batches, y_batches = [], []
                for x_tensors, y_tensors in dataloader:
                    x_batches.append(x_tensors[0])
                    y_batches.append(y_tensors[0])
                assert_tensors_almost_equal_array(
                    x_batches, x_data, x_tensor_kind, batch_size, to_dense
                )
                assert_tensors_almost_equal_array(
                    y_batches, y_data, y_tensor_kind, batch_size, to_dense
                )
