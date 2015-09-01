
"""Import Orders: Shopping Cart Tables from the LMS, Orders from Otto."""

import luigi
import luigi.hdfs

from edx.analytics.tasks.util.overwrite import OverwriteOutputMixin
from edx.analytics.tasks.util.hive import HiveTableFromQueryTask, HivePartition
from edx.analytics.tasks.database_imports import (
    DatabaseImportMixin,
    ImportShoppingCartCertificateItem,
    ImportShoppingCartCourseRegistrationCodeItem,
    ImportShoppingCartDonation,
    ImportShoppingCartOrder,
    ImportShoppingCartOrderItem,
    ImportShoppingCartPaidCourseRegistration,
    ImportEcommerceUser,
    ImportProductCatalog,
    ImportProductCatalogClass,
    ImportProductCatalogAttributes,
    ImportProductCatalogAttributeValues,
    ImportOrderOrderHistory,
    ImportOrderHistoricalLine,
    ImportCurrentBasketState,
    ImportCurrentOrderState,
    ImportCurrentOrderLineState,
    ImportCurrentOrderLineAttributeState,
    ImportCurrentOrderLinePriceState,
    ImportOrderPaymentEvent,
    ImportPaymentSource,
    ImportPaymentTransactions,
    ImportPaymentProcessorResponse,
    ImportCurrentRefundRefundState,
    ImportCurrentRefundRefundLineState,
    ImportRefundHistoricalRefund,
    ImportRefundHistoricalRefundLine,
    ImportAuthUserTask,
)


class PullFromShoppingCartTablesTask(DatabaseImportMixin, OverwriteOutputMixin, luigi.WrapperTask):
    """Imports a set of shopping cart database tables from an external LMS RDBMS into a destination directory."""

    def requires(self):
        kwargs = {
            'destination': self.destination,
            'credentials': self.credentials,
            'num_mappers': self.num_mappers,
            'verbose': self.verbose,
            # JAB!!
            # 'import_date': self.import_date,
            'import_date': self.import_date,
            'overwrite': self.overwrite,
            'database': self.database,
        }
        yield (
            # Original shopping cart tables.
            ImportShoppingCartOrder(**kwargs),
            ImportShoppingCartOrderItem(**kwargs),
            ImportShoppingCartCertificateItem(**kwargs),
            ImportShoppingCartPaidCourseRegistration(**kwargs),
            ImportShoppingCartDonation(**kwargs),
            ImportShoppingCartCourseRegistrationCodeItem(**kwargs),
            ImportAuthUserTask(**kwargs),
        )

    def output(self):
        return [task.output() for task in self.requires()]


class PullFromEcommerceTablesTask(DatabaseImportMixin, OverwriteOutputMixin, luigi.WrapperTask):
    """Imports a set of ecommerce tables from an external database into a destination directory."""

    destination = luigi.Parameter(
        default_from_config={'section': 'otto-database-import', 'name': 'destination'}
    )
    credentials = luigi.Parameter(
        default_from_config={'section': 'otto-database-import', 'name': 'credentials'}
    )
    database = luigi.Parameter(
        default_from_config={'section': 'otto-database-import', 'name': 'database'}
    )
    import_date = luigi.DateParameter()

    def requires(self):
        kwargs = {
            'destination': self.destination,
            'credentials': self.credentials,
            'num_mappers': self.num_mappers,
            'verbose': self.verbose,
            'import_date': self.import_date,
            'overwrite': self.overwrite,
            'database': self.database,
        }
        yield (
            # Otto User Table
            ImportEcommerceUser(**kwargs),

            # Otto Product Tables.
            ImportProductCatalog(**kwargs),
            ImportProductCatalogClass(**kwargs),
            ImportProductCatalogAttributes(**kwargs),
            ImportProductCatalogAttributeValues(**kwargs),

            # Otto Order History Tables.
            ImportOrderOrderHistory(**kwargs),
            ImportOrderHistoricalLine(**kwargs),

            # Otto Current State and Line Item Tables.
            ImportCurrentBasketState(**kwargs),
            ImportCurrentOrderState(**kwargs),
            ImportCurrentOrderLineState(**kwargs),
            ImportCurrentOrderLineAttributeState(**kwargs),
            ImportCurrentOrderLinePriceState(**kwargs),

            # Otto Payment Tables.
            ImportOrderPaymentEvent(**kwargs),
            ImportPaymentSource(**kwargs),
            ImportPaymentTransactions(**kwargs),
            ImportPaymentProcessorResponse(**kwargs),

            # Otto Refund Tables.
            ImportCurrentRefundRefundState(**kwargs),
            ImportCurrentRefundRefundLineState(**kwargs),
            ImportRefundHistoricalRefund(**kwargs),
            ImportRefundHistoricalRefundLine(**kwargs),
        )

    def output(self):
        return [task.output() for task in self.requires()]


class OrderTableTask(DatabaseImportMixin, HiveTableFromQueryTask):

    otto_credentials = luigi.Parameter(
        default_from_config={'section': 'otto-database-import', 'name': 'credentials'}
    )
    otto_database = luigi.Parameter(
        default_from_config={'section': 'otto-database-import', 'name': 'database'}
    )
    interval = luigi.DateIntervalParameter()

    def requires(self):
        kwargs = {
            'num_mappers': self.num_mappers,
            'verbose': self.verbose,
            'import_date': self.interval.date_b.isoformat(),
            # JAB
            # 'import_date': self.import_date,
            'overwrite': self.overwrite,
        }
        yield (
            PullFromEcommerceTablesTask(
                destination=self.destination,
                credentials=self.otto_credentials,
                database=self.otto_database,
                **kwargs
            ),
            PullFromShoppingCartTablesTask(
                destination=self.destination,
                credentials=self.credentials,
                database=self.database,
                **kwargs
            )
        )

    @property
    def table(self):
        return 'order'

    @property
    def columns(self):
        return [
            ('order_processor', 'STRING'),
            ('user_id', 'INT'),
            ('order_id', 'INT'),
            ('line_item_id', 'INT'),
            ('line_item_product_id', 'INT'),
            ('line_item_price', 'DECIMAL'),
            ('line_item_unit_price', 'DECIMAL'),
            ('line_item_quantity', 'INT'),
            ('product_class', 'STRING'),
            ('course_key', 'STRING'),
            ('product_detail', 'STRING'),
            ('username', 'STRING'),
            ('user_email', 'STRING'),
            ('date_placed', 'TIMESTAMP'),
            ('iso_currency_code', 'STRING'),
            ('status', 'STRING'),
            ('refunded_amount', 'DECIMAL'),
            ('refunded_quantity', 'INT'),
            ('payment_ref_id', 'STRING'),
        ]

    @property
    def partition(self):
        # return HivePartition('dt', self.import_date.isoformat())  # pylint: disable=no-member
        return HivePartition('dt', self.interval.date_b.isoformat()) # pylint: disable=no-member

    @property
    def insert_query(self):
        return """
            SELECT
                combined.*
            FROM (
                -- Otto Records
                SELECT
                    "otto" AS order_processor,
                    o.user_id AS user_id,
                    ol.order_id AS order_id,
                    ol.id AS line_item_id,
                    ol.product_id AS line_item_product_id,

                    -- Price charged to the customer after all surcharges and discounts
                    ol.line_price_incl_tax AS line_item_price,

                    ol.unit_price_incl_tax AS line_item_unit_price,
                    ol.quantity AS line_item_quantity,
                    cpc.slug AS product_class,
                    ckval.value_text AS course_key,
                    ctval.value_text AS product_detail,
                    u.username AS username,
                    u.email AS user_email,
                    o.date_placed AS date_placed,
                    o.currency AS iso_currency_code,

                    -- If a refund was found, mark this order as refunded
                    CASE
                        WHEN r.order_line_id IS NOT NULL THEN "refunded"
                        ELSE "purchased"
                    END AS status,
                    r.refunded_amount AS refunded_amount,
                    r.refunded_quantity AS refunded_quantity,

                    -- The EDX-1XXXX identifier is used to find transactions associated with this order
                    o.number AS payment_ref_id

                FROM order_line ol
                JOIN order_order o ON o.id = ol.order_id
                JOIN ecommerce_user u ON u.id = o.user_id

                -- Order lines are associated with "child" products
                JOIN catalogue_product cp ON cp.id = ol.product_id

                -- Product classes are associated with "parent" products, so find the parent for this product
                JOIN catalogue_product parent ON parent.id = cp.parent_id
                JOIN catalogue_productclass cpc ON cpc.id = parent.product_class_id

                -- Product attributes are effectively a key value store. Each product class has a set of attributes
                -- associated with it that store additional data that is class-specific. For example, a T-shirt might
                -- store size information.

                -- For "seat" product class, line items will have a "course_key" attribute which will contain the course
                -- key for the course that the user purchased a seat for
                LEFT OUTER JOIN catalogue_productattribute ckat ON ckat.product_class_id = parent.product_class_id AND ckat.code = "course_key"
                LEFT OUTER JOIN catalogue_productattributevalue ckval ON ckval.attribute_id = ckat.id AND ckval.product_id = cp.id

                -- For the "seat" product class, line items will have a "certificate_type" attribute that will contain
                -- the type of certificate they purchased. For example: "verified" or "honor".
                LEFT OUTER JOIN catalogue_productattribute ctat ON ctat.product_class_id = parent.product_class_id AND ctat.code = "certificate_type"
                LEFT OUTER JOIN catalogue_productattributevalue ctval ON ctval.attribute_id = ctat.id AND ctval.product_id = cp.id

                -- If the quantity > 1 for a particular line item it is possible that multiple refunds might be issued
                -- against it. In this case just sum all of the complete refunds to figure out the number of items that
                -- have been refunded and the dollar amount of all of those refunds.
                LEFT OUTER JOIN (
                    SELECT
                        order_line_id,
                        SUM(line_credit_excl_tax) AS refunded_amount,
                        SUM(quantity) AS refunded_quantity
                    FROM refund_refundline
                    WHERE status = "Complete"
                    GROUP BY order_line_id
                ) r ON r.order_line_id = ol.id

                -- Only process complete orders
                WHERE ol.status = "Complete"

                UNION ALL

                -- Legacy Shopping Cart Records
                SELECT
                    'shoppingcart' AS order_processor,
                    o.user_id AS user_id,
                    oi.order_id AS order_id,
                    oi.id AS line_item_id,

                    -- LMS product types are identified by the table pointing to the orderitem
                    -- Assign ID numbers based on the pointing table
                    CASE
                        WHEN ci.orderitem_ptr_id IS NOT NULL THEN 1
                        WHEN pcr.orderitem_ptr_id IS NOT NULL THEN 2
                        WHEN crc.orderitem_ptr_id IS NOT NULL THEN 3
                        WHEN d.orderitem_ptr_id IS NOT NULL THEN 4
                    END AS line_item_product_id,

                    -- The total cost is not stored, so we compute it
                    -- Note that this is the amount charged to the credit card after all discounts
                    (oi.qty * oi.unit_cost) AS line_item_price,
                    oi.unit_cost AS line_item_unit_price,
                    oi.qty AS line_item_quantity,
                    CASE
                        WHEN ci.orderitem_ptr_id IS NOT NULL THEN 'seat'          -- verified certificate
                        WHEN pcr.orderitem_ptr_id IS NOT NULL THEN 'seat'         -- single user registration
                        WHEN crc.orderitem_ptr_id IS NOT NULL THEN 'reg-code'     -- registration codes
                        WHEN d.orderitem_ptr_id IS NOT NULL THEN 'donation'       -- donation
                    END AS product_class,
                    CASE
                        WHEN ci.orderitem_ptr_id IS NOT NULL THEN ci.course_id    -- the course the certificate is for
                        WHEN pcr.orderitem_ptr_id IS NOT NULL THEN pcr.course_id  -- the course the user registered in
                        WHEN crc.orderitem_ptr_id IS NOT NULL THEN crc.course_id  -- the course the registration codes were generated for
                        WHEN d.orderitem_ptr_id IS NOT NULL THEN d.course_id      -- the course that the user donated to (may be NULL)
                    END AS course_key,
                    CASE
                        WHEN ci.orderitem_ptr_id IS NOT NULL THEN ci.mode         -- always "verified"
                        WHEN pcr.orderitem_ptr_id IS NOT NULL THEN pcr.mode       -- always "honor" even though the user paid for the seat
                        WHEN crc.orderitem_ptr_id IS NOT NULL THEN crc.mode       -- always "honor"
                    END AS product_detail,
                    au.username as username,
                    au.email as user_email,
                    o.purchase_time AS date_placed,
                    UPPER(o.currency) AS iso_currency_code,

                    -- Either "purchased" or "refunded"
                    oi.status AS status,

                    -- We don't currently support partial refunds so the refund will always encompass
                    -- the complete line item quantity and amount
                    IF(oi.status = 'refunded', oi.qty * oi.unit_cost, NULL) AS refunded_amount,
                    IF(oi.status = 'refunded', oi.qty, NULL) AS refunded_quantity,
                    oi.order_id AS payment_ref_id
                FROM shoppingcart_orderitem oi
                JOIN shoppingcart_order o ON o.id = oi.order_id
                JOIN auth_user au ON au.id = o.user_id

                -- These tables contain details pertaining to the particular type of product purchased
                -- exactly one of these joins should resolve.
                LEFT OUTER JOIN shoppingcart_certificateitem ci ON ci.orderitem_ptr_id = oi.id
                LEFT OUTER JOIN shoppingcart_paidcourseregistration pcr ON pcr.orderitem_ptr_id = oi.id
                LEFT OUTER JOIN shoppingcart_courseregcodeitem crc ON crc.orderitem_ptr_id = oi.id
                LEFT OUTER JOIN shoppingcart_donation d ON d.orderitem_ptr_id = oi.id

                -- Ignore "cart", "defunct-cart" and "paying" statuses since they won't have corresponding transactions
                WHERE oi.status IN ('purchased', 'refunded')
            ) combined;
        """
