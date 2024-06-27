import django_filters
from django.shortcuts import render
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR
from rest_framework.views import APIView
from indexer.models import Ton20Tick, Ton20Wallet, TransactionStatus, Ton20StateSerialized
from indexer.serializers import Ton20TickSerializer, Ton20WalletSerializer, TransactionStatusSerializer, \
    Ton20StateSerializedSerializer
from tonpy import Address
from django_filters import rest_framework as filters
from loguru import logger

from rest_framework.filters import OrderingFilter


def fix_address(address):
    if ':' in address:
        to_addr = address.split(':')
        return f"{to_addr[0]}:{to_addr[1].zfill(64)}"
    else:
        return address


class WalletByAddressView(APIView):
    serializer_class = Ton20WalletSerializer
    pagination_class = None

    def get(self, request, address, format=None):
        a = Address(fix_address(address))
        wallets = Ton20Wallet.objects.filter(wallet=f"{a.workchain}:{a.address}")
        serializer = Ton20WalletSerializer(wallets, many=True)
        return Response(serializer.data)


class WalletByAddressAndTickView(APIView):
    serializer_class = Ton20WalletSerializer
    pagination_class = None

    def get(self, request, address, tick, format=None):
        a = Address(fix_address(address))
        wallets = Ton20Wallet.objects.filter(wallet=f"{a.workchain}:{a.address}")
        serializer = Ton20WalletSerializer(wallets, many=True)
        return Response(serializer.data)


class TickByTickView(APIView):
    serializer_class = Ton20TickSerializer
    pagination_class = None

    def get(self, request, tick, format=None):
        ticks = Ton20Tick.objects.filter(tick=tick)
        serializer = Ton20TickSerializer(ticks, many=True)
        return Response(serializer.data)


class CustomTickFilter(filters.FilterSet):
    ticks = filters.CharFilter(method='filter_by_ticks')

    class Meta:
        model = Ton20Tick
        fields = []

    def filter_by_ticks(self, queryset, name, value):
        tick_list = value.split(',')
        return queryset.filter(tick__in=tick_list)


class LatestStateBOCView(APIView):
    serializer_class = Ton20StateSerializedSerializer
    pagination_class = None

    def get(self, request, *args, **kwargs):
        try:
            latest_state = Ton20StateSerialized.objects.latest('in_msg_created_lt')
            serializer = Ton20StateSerializedSerializer(latest_state)
            return Response(serializer.data, status=HTTP_200_OK)
        except Ton20StateSerialized.DoesNotExist:
            logger.error("No records found")
            return Response({"error": "No records found"}, status=HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            return Response({"error": "Internal server error"}, status=HTTP_500_INTERNAL_SERVER_ERROR)


class Ton20TickListView(generics.ListAPIView):
    queryset = Ton20Tick.objects.all()
    serializer_class = Ton20TickSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = CustomTickFilter


class TransactionStatusFilter(django_filters.FilterSet):
    success = django_filters.BooleanFilter(field_name='success')
    op_code = django_filters.CharFilter(field_name='op_code')

    class Meta:
        model = TransactionStatus
        fields = ['success', 'op_code']


class TransactionListView(generics.ListAPIView):
    serializer_class = TransactionStatusSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransactionStatusFilter
    ordering_fields = ['tick', 'memo']

    def get_queryset(self):
        initiator = self.kwargs['initiator']
        return TransactionStatus.objects.order_by('-in_msg_created_lt').filter(initiator=initiator)


class TransactionByTickView(generics.ListAPIView):
    serializer_class = TransactionStatusSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransactionStatusFilter

    def get_queryset(self):
        tick = self.kwargs['tick']
        return TransactionStatus.objects.order_by('-in_msg_created_lt').filter(tick=tick)


class TransactionByHashView(generics.RetrieveAPIView):
    serializer_class = TransactionStatusSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransactionStatusFilter
    pagination_class = None

    def get_queryset(self):
        transaction_hash = self.kwargs['transaction_hash']
        return TransactionStatus.objects.order_by('-in_msg_created_lt').filter(transaction_hash=transaction_hash)
