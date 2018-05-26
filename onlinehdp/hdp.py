"""
online hdp with lazy update
part of code is adapted from Matt's online lda code
"""
import numpy as np
import scipy.special as sp
from onlinehdp import utils

import random

meanchangethresh = 0.00001
random_seed = 999931111
np.random.seed(random_seed)
random.seed(random_seed)
min_adding_noise_point = 10
min_adding_noise_ratio = 1
mu0 = 0.3
rhot_bound = 0.0


def dirichlet_expectation(alpha):
    """
    For a vector theta ~ Dir(alpha), computes E[log(theta)] given alpha.
    """
    if len(alpha.shape) == 1:
        return sp.psi(alpha) - sp.psi(np.sum(alpha))
    return sp.psi(alpha) - sp.psi(np.sum(alpha, 1))[:, np.newaxis]


def expect_log_sticks(sticks):
    """
    For stick-breaking hdp, this returns the E[log(sticks)] 
    """
    dig_sum = sp.psi(np.sum(sticks, 0))
    ElogW = sp.psi(sticks[0]) - dig_sum
    Elog1_W = sp.psi(sticks[1]) - dig_sum

    n = len(sticks[0]) + 1
    Elogsticks = np.zeros(n)
    Elogsticks[0:n - 1] = ElogW
    Elogsticks[1:] = Elogsticks[1:] + np.cumsum(Elog1_W)
    return Elogsticks


def lda_e_step_half(doc, alpha, Elogbeta, split_ratio):

    n_train = int(doc.length * split_ratio)

    # split the document
    words_train = doc.words[:n_train]
    counts_train = doc.counts[:n_train]
    words_test = doc.words[n_train:]
    counts_test = doc.counts[n_train:]

    gamma = np.ones(len(alpha))
    expElogtheta = np.exp(dirichlet_expectation(gamma))

    expElogbeta = np.exp(Elogbeta)
    expElogbeta_train = expElogbeta[:, words_train]
    phinorm = np.dot(expElogtheta, expElogbeta_train) + 1e-100
    counts = np.array(counts_train)
    iteration = 0
    max_iter = 100
    while iteration < max_iter:
        lastgamma = gamma
        iteration += 1
        gamma = alpha + expElogtheta * np.dot(counts / phinorm,
                                              expElogbeta_train.T)
        Elogtheta = dirichlet_expectation(gamma)
        expElogtheta = np.exp(Elogtheta)
        phinorm = np.dot(expElogtheta, expElogbeta_train) + 1e-100
        meanchange = np.mean(abs(gamma - lastgamma))
        if meanchange < meanchangethresh:
            break
    gamma = gamma / np.sum(gamma)
    counts = np.array(counts_test)
    expElogbeta_test = expElogbeta[:, words_test]
    score = np.sum(counts * np.log(np.dot(gamma, expElogbeta_test) + 1e-100))

    return score, np.sum(counts), gamma


def lda_e_step_split(doc, alpha, beta, max_iter=100):
    half_len = int(doc.length / 2) + 1
    idx_train = [2 * i for i in range(half_len) if 2 * i < doc.length]
    idx_test = [2 * i + 1 for i in range(half_len) if 2 * i + 1 < doc.length]

    # split the document
    words_train = [doc.words[i] for i in idx_train]
    counts_train = [doc.counts[i] for i in idx_train]
    words_test = [doc.words[i] for i in idx_test]
    counts_test = [doc.counts[i] for i in idx_test]

    gamma = np.ones(len(alpha))
    expElogtheta = np.exp(dirichlet_expectation(gamma))
    betad = beta[:, words_train]
    phinorm = np.dot(expElogtheta, betad) + 1e-100
    counts = np.array(counts_train)
    iteration = 0
    while iteration < max_iter:
        lastgamma = gamma
        iteration += 1
        gamma = alpha + expElogtheta * np.dot(counts / phinorm, betad.T)
        Elogtheta = dirichlet_expectation(gamma)
        expElogtheta = np.exp(Elogtheta)
        phinorm = np.dot(expElogtheta, betad) + 1e-100
        meanchange = np.mean(abs(gamma - lastgamma))
        if meanchange < meanchangethresh:
            break

    gamma = gamma / np.sum(gamma)
    counts = np.array(counts_test)
    betad = beta[:, words_test]
    score = np.sum(counts * np.log(np.dot(gamma, betad) + 1e-100))

    return score, np.sum(counts), gamma


def lda_e_step(doc, alpha, beta, max_iter=100):
    gamma = np.ones(len(alpha))
    expElogtheta = np.exp(dirichlet_expectation(gamma))
    betad = beta[:, doc.words]
    phinorm = np.dot(expElogtheta, betad) + 1e-100
    counts = np.array(doc.counts)
    iteration = 0
    while iteration < max_iter:
        lastgamma = gamma
        iteration += 1
        gamma = alpha + expElogtheta * np.dot(counts / phinorm, betad.T)
        Elogtheta = dirichlet_expectation(gamma)
        expElogtheta = np.exp(Elogtheta)
        phinorm = np.dot(expElogtheta, betad) + 1e-100
        meanchange = np.mean(abs(gamma - lastgamma))
        if meanchange < meanchangethresh:
            break

    likelihood = np.sum(counts * np.log(phinorm))
    likelihood += np.sum((alpha - gamma) * Elogtheta)
    likelihood += np.sum(sp.gammaln(gamma) - sp.gammaln(alpha))
    likelihood += sp.gammaln(np.sum(alpha)) - sp.gammaln(np.sum(gamma))

    return likelihood, gamma


class suff_stats:
    def __init__(self, T, Wt, Dt):
        self.m_batchsize = Dt
        self.m_var_sticks_ss = np.zeros(T)
        self.m_var_beta_ss = np.zeros((T, Wt))

    def set_zero(self):
        self.m_var_sticks_ss.fill(0.0)
        self.m_var_beta_ss.fill(0.0)


class online_hdp:
    ''' hdp model using stick breaking'''

    def __init__(self,
                 T,
                 K,
                 D,
                 W,
                 eta,
                 alpha,
                 gamma,
                 kappa,
                 tau,
                 scale=1.0,
                 adding_noise=False):
        """
        this follows the convention of the HDP paper
        gamma: first level concentration
        alpha: second level concentration
        eta: the topic Dirichlet
        T: top level truncation level
        K: second level truncation level
        W: size of vocab
        D: number of documents in the corpus
        kappa: learning rate
        tau: slow down parameter
        """

        self.m_W = W
        self.m_D = D
        self.m_T = T
        self.m_K = K
        self.m_alpha = alpha
        self.m_gamma = gamma

        self.m_var_sticks = np.zeros((2, T - 1))
        self.m_var_sticks[0] = 1.0
        #self.m_var_sticks[1] = self.m_gamma
        # make a uniform at beginning
        self.m_var_sticks[1] = list(range(T - 1, 0, -1))

        self.m_varphi_ss = np.zeros(T)

        self.m_lambda = np.random.gamma(1.0, 1.0,
                                        (T, W)) * D * 100 / (T * W) - eta
        self.m_eta = eta
        self.m_Elogbeta = dirichlet_expectation(self.m_eta + self.m_lambda)

        self.m_tau = tau + 1
        self.m_kappa = kappa
        self.m_scale = scale
        self.m_updatect = 0
        self.m_status_up_to_date = True
        self.m_adding_noise = adding_noise
        self.m_num_docs_parsed = 0

        # Timestamps and normalizers for lazy updates
        self.m_timestamp = np.zeros(self.m_W, dtype=int)
        self.m_r = [0]
        self.m_lambda_sum = np.sum(self.m_lambda, axis=1)

    def process_documents(self,
                          docs,
                          var_converge,
                          unseen_ids=None,
                          update=True,
                          opt_o=True):
        if unseen_ids is None:
            unseen_ids = []
        # Find the unique words in this mini-batch of documents...
        self.m_num_docs_parsed += len(docs)
        adding_noise = False
        adding_noise_point = min_adding_noise_point

        if self.m_adding_noise:
            if float(adding_noise_point) / len(docs) < min_adding_noise_ratio:
                adding_noise_point = min_adding_noise_ratio * len(docs)

            if self.m_num_docs_parsed % adding_noise_point == 0:
                adding_noise = True

        unique_words = dict()
        word_list = []
        if adding_noise:
            word_list = list(range(self.m_W))
            for w in word_list:
                unique_words[w] = w
        else:
            for doc in docs:
                for w in doc.words:
                    if w not in unique_words:
                        unique_words[w] = len(unique_words)
                        word_list.append(w)
        Wt = len(word_list)  # length of words in these documents

        # ...and do the lazy updates on the necessary columns of lambda
        rw = np.array([self.m_r[t] for t in self.m_timestamp[word_list]])
        self.m_lambda[:, word_list] *= np.exp(self.m_r[-1] - rw)
        self.m_Elogbeta[:, word_list] = \
            sp.psi(self.m_eta + self.m_lambda[:, word_list]) - \
            sp.psi(self.m_W*self.m_eta + self.m_lambda_sum[:, np.newaxis])

        ss = suff_stats(self.m_T, Wt, len(docs))

        Elogsticks_1st = expect_log_sticks(self.m_var_sticks)  # global sticks

        # run variational inference on some new docs
        score = 0.0
        count = 0
        unseen_score = 0.0
        unseen_count = 0
        for i, doc in enumerate(docs):
            doc_score = self.doc_e_step(doc, ss, Elogsticks_1st, unique_words,
                                        var_converge)
            count += doc.total
            score += doc_score
            if i in unseen_ids:
                unseen_score += doc_score
                unseen_count += doc.total

        if adding_noise:
            print("adding noise at this stage...")

            noise = np.random.gamma(1.0, 1.0, ss.m_var_beta_ss.shape)
            noise_sum = np.sum(noise, axis=1)
            ratio = np.sum(ss.m_var_beta_ss, axis=1) / noise_sum
            noise = noise * ratio[:, np.newaxis]

            mu = mu0 * 1000.0 / (self.m_updatect + 1000)

            ss.m_var_beta_ss = ss.m_var_beta_ss * (1.0 - mu) + noise * mu

        if update:
            self.update_lambda(ss, word_list, opt_o)

        return score, count, unseen_score, unseen_count

    def optimal_ordering(self):
        """
        ordering the topics
        """
        idx = [i for i in reversed(np.argsort(self.m_lambda_sum))]
        self.m_varphi_ss = self.m_varphi_ss[idx]
        self.m_lambda = self.m_lambda[idx, :]
        self.m_lambda_sum = self.m_lambda_sum[idx]
        self.m_Elogbeta = self.m_Elogbeta[idx, :]

    def doc_e_step(self,
                   doc,
                   ss,
                   Elogsticks_1st,
                   unique_words,
                   var_converge,
                   max_iter=100):
        """
        e step for a single doc
        """

        batchids = [unique_words[id] for id in doc.words]

        Elogbeta_doc = self.m_Elogbeta[:, doc.words]
        # very similar to the hdp equations
        v = np.zeros((2, self.m_K - 1))
        v[0] = 1.0
        v[1] = self.m_alpha

        # The following line is of no use.
        Elogsticks_2nd = expect_log_sticks(v)

        # back to the uniform
        phi = np.ones((len(doc.words), self.m_K)) * 1.0 / self.m_K

        likelihood = 0.0
        old_likelihood = -1e100
        converge = 1.0

        iteration = 0

        # TODO: figure out what's going on with this, why is it used outside the loop?
        var_phi = 0.0
        # not yet support second level optimization yet, to be done in the future
        while iteration < max_iter and (converge < 0.0
                                        or converge > var_converge):
            ### update variational parameters
            # var_phi
            if iteration < 3:
                var_phi = np.dot(phi.T, (Elogbeta_doc * doc.counts).T)
                (log_var_phi, log_norm) = utils.log_normalize(var_phi)
                var_phi = np.exp(log_var_phi)
            else:
                var_phi = np.dot(
                    phi.T, (Elogbeta_doc * doc.counts).T) + Elogsticks_1st
                (log_var_phi, log_norm) = utils.log_normalize(var_phi)
                var_phi = np.exp(log_var_phi)

            # phi
            if iteration < 3:
                phi = np.dot(var_phi, Elogbeta_doc).T
                (log_phi, log_norm) = utils.log_normalize(phi)
                phi = np.exp(log_phi)
            else:
                phi = np.dot(var_phi, Elogbeta_doc).T + Elogsticks_2nd
                (log_phi, log_norm) = utils.log_normalize(phi)
                phi = np.exp(log_phi)

            # v
            phi_all = phi * np.array(doc.counts)[:, np.newaxis]
            v[0] = 1.0 + np.sum(phi_all[:, :self.m_K - 1], 0)
            phi_cum = np.flipud(np.sum(phi_all[:, 1:], 0))
            v[1] = self.m_alpha + np.flipud(np.cumsum(phi_cum))
            Elogsticks_2nd = expect_log_sticks(v)

            likelihood = 0.0
            # compute likelihood
            # var_phi part/ C in john's notation
            likelihood += np.sum((Elogsticks_1st - log_var_phi) * var_phi)

            # v part/ v in john's notation, john's beta is alpha here
            log_alpha = np.log(self.m_alpha)
            likelihood += (self.m_K - 1) * log_alpha
            dig_sum = sp.psi(np.sum(v, 0))
            likelihood += np.sum(
                (np.array([1.0, self.m_alpha])[:, np.newaxis] - v) *
                (sp.psi(v) - dig_sum))
            likelihood -= np.sum(sp.gammaln(np.sum(v, 0))) - np.sum(
                sp.gammaln(v))

            # Z part
            likelihood += np.sum((Elogsticks_2nd - log_phi) * phi)

            # X part, the data part
            likelihood += np.sum(
                phi.T * np.dot(var_phi, Elogbeta_doc * doc.counts))

            converge = (likelihood - old_likelihood) / abs(old_likelihood)
            old_likelihood = likelihood

            if converge < -0.000001:
                print("warning, likelihood is decreasing!")

            iteration += 1

        # update the suff_stat ss
        # this time it only contains information from one doc
        ss.m_var_sticks_ss += np.sum(var_phi, 0)
        ss.m_var_beta_ss[:, batchids] += np.dot(var_phi.T, phi.T * doc.counts)

        return likelihood

    def update_lambda(self, sstats, word_list, opt_o):

        self.m_status_up_to_date = False
        if len(word_list) == self.m_W:
            self.m_status_up_to_date = True
        # rhot will be between 0 and 1, and says how much to weight
        # the information we got from this mini-batch.
        rhot = self.m_scale * pow(self.m_tau + self.m_updatect, -self.m_kappa)
        if rhot < rhot_bound:
            rhot = rhot_bound
        self.m_rhot = rhot

        # Update appropriate columns of lambda based on documents.
        self.m_lambda[:, word_list] = self.m_lambda[:, word_list] * (1-rhot) + \
            rhot * self.m_D * sstats.m_var_beta_ss / sstats.m_batchsize
        self.m_lambda_sum = (1-rhot) * self.m_lambda_sum+ \
            rhot * self.m_D * np.sum(sstats.m_var_beta_ss, axis=1) / sstats.m_batchsize

        self.m_updatect += 1
        self.m_timestamp[word_list] = self.m_updatect
        self.m_r.append(self.m_r[-1] + np.log(1 - rhot))

        self.m_varphi_ss = (1.0-rhot) * self.m_varphi_ss + rhot * \
               sstats.m_var_sticks_ss * self.m_D / sstats.m_batchsize

        if opt_o:
            self.optimal_ordering()

        ## update top level sticks
        self.m_var_sticks[0] = self.m_varphi_ss[:self.m_T - 1] + 1.0
        var_phi_sum = np.flipud(self.m_varphi_ss[1:])
        self.m_var_sticks[1] = np.flipud(np.cumsum(var_phi_sum)) + self.m_gamma

    def update_expectations(self):
        """
        Since we're doing lazy updates on lambda, at any given moment
        the current state of lambda may not be accurate. This function
        updates all of the elements of lambda and Elogbeta so that if (for
        example) we want to print out the topics we've learned we'll get the
        correct behavior.
        """
        for w in range(self.m_W):
            self.m_lambda[:, w] *= np.exp(
                self.m_r[-1] - self.m_r[self.m_timestamp[w]])
        self.m_Elogbeta = sp.psi(self.m_eta + self.m_lambda) - \
            sp.psi(self.m_W*self.m_eta + self.m_lambda_sum[:, np.newaxis])
        self.m_timestamp[:] = self.m_updatect
        self.m_status_up_to_date = True

    def save_topics(self, filename):
        if not self.m_status_up_to_date:
            self.update_expectations()
        f = open(filename, "w")
        betas = self.m_lambda + self.m_eta
        for beta in betas:
            line = ' '.join([str(x) for x in beta])
            f.write(line + '\n')
        f.close()

    def hdp_to_lda(self):
        # compute the lda almost equivalent hdp.
        # alpha
        if not self.m_status_up_to_date:
            self.update_expectations()

        sticks = self.m_var_sticks[0] / (
            self.m_var_sticks[0] + self.m_var_sticks[1])
        alpha = np.zeros(self.m_T)
        left = 1.0
        for i in range(0, self.m_T - 1):
            alpha[i] = sticks[i] * left
            left = left - alpha[i]
        alpha[self.m_T - 1] = left
        alpha = alpha * self.m_alpha
        #alpha = alpha * self.m_gamma

        # beta
        beta = (self.m_lambda + self.m_eta) / (
            self.m_W * self.m_eta + self.m_lambda_sum[:, np.newaxis])

        return alpha, beta

    def infer_only(self, docs, half_train_half_test=False, split_ratio=0.9):
        # be sure to run update_expectations()
        sticks = self.m_var_sticks[0] / (
            self.m_var_sticks[0] + self.m_var_sticks[1])
        alpha = np.zeros(self.m_T)
        left = 1.0
        for i in range(0, self.m_T - 1):
            alpha[i] = sticks[i] * left
            left = left - alpha[i]
        alpha[self.m_T - 1] = left
        #alpha = alpha * self.m_gamma
        score = 0.0
        count = 0.0
        for doc in docs:
            if half_train_half_test:
                (s, c, gamma) = lda_e_step_half(doc, alpha, self.m_Elogbeta,
                                                split_ratio)
                score += s
                count += c
            else:
                score += lda_e_step(doc, alpha, np.exp(self.m_Elogbeta))
                count += doc.total
        return score, count
